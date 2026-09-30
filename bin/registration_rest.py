from __future__ import annotations

import configparser
import json
import logging
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from splunk.persistconn.application import PersistentServerConnectionApplication

APP = "SA-ctf_registration"
BASE = Path(os.environ.get("SPLUNK_HOME", "/opt/splunk")) / "etc" / "apps" / APP
BIN = BASE / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

from registration_content import parse_ctf_content

from registration_core import (
    event_state,
    parse_bool,
    parse_roles,
    registration_state,
    validate_event,
    validate_registration,
)

LOG_PATH = Path(os.environ.get("SPLUNK_HOME", "/opt/splunk")) / "var" / "log" / "splunk" / "ctf_registration.log"
logger = logging.getLogger("ctf_registration")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(str(LOG_PATH))
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)

DEFAULT_CONFIG = BASE / "default" / "ctf_registration.conf"
LOCAL_CONFIG = BASE / "local" / "ctf_registration.conf"
SECRETS_CONFIG = BASE / "local" / "registration_secrets.conf"

ADMIN_ROLES = {"admin", "ctf_admin", "ctf_registration_admin"}
EVENTS_COLLECTION = "ctf_events"
REGISTRATIONS_COLLECTION = "ctf_registrations"
SCOREBOARD_APP = "SA-ctf_scoreboard"
SCOREBOARD_ADMIN_APP = "SA-ctf_scoreboard_admin"
CONTENT_ADMIN_ROLES = {"admin", "ctf_admin"}

CONTENT_TARGETS = {
    "questions": (SCOREBOARD_ADMIN_APP, "ctf_questions", ("Number",)),
    "answers": (SCOREBOARD_ADMIN_APP, "ctf_answers", ("Number",)),
    "hints": (SCOREBOARD_ADMIN_APP, "ctf_hints", ("Number", "HintNumber")),
}


def _json_response(payload, status=200):
    return {"payload": payload, "status": status}


def _pairs_to_dict(pairs):
    result = {}
    for item in pairs or []:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            result[str(item[0])] = str(item[1])
        elif isinstance(item, dict):
            name = item.get("name")
            if name is not None:
                result[str(name)] = str(item.get("value", ""))
    return result


def _load_general():
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str.lower
    parser.read([str(DEFAULT_CONFIG), str(LOCAL_CONFIG)])
    if not parser.has_section("general"):
        raise RuntimeError("Missing [general] configuration")
    return dict(parser.items("general"))


def _load_secret():
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(str(SECRETS_CONFIG))
    if parser.has_section("writer"):
        return parser.get("writer", "password", fallback="").strip()
    return ""


def _urlopen_json(url, method="GET", token=None, data=None, headers=None):
    request_headers = {"Accept": "application/json"}
    if token:
        request_headers["Authorization"] = "Splunk " + token
    if headers:
        request_headers.update(headers)

    body = None
    if data is not None:
        if isinstance(data, (dict, list)):
            body = json.dumps(data).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        elif isinstance(data, str):
            body = data.encode("utf-8")
        else:
            body = data

    req = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    context = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, context=context, timeout=15) as response:
            content = response.read().decode("utf-8")
            return json.loads(content) if content else {}
    except urllib.error.HTTPError as exc:
        content = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Splunk REST returned HTTP {exc.code}: {content}") from exc


def _service_token(rest_uri, username):
    password = _load_secret()
    if not username or not password:
        return None
    body = urllib.parse.urlencode(
        {"username": username, "password": password, "output_mode": "json"}
    ).encode("utf-8")
    req = urllib.request.Request(
        rest_uri.rstrip("/") + "/services/auth/login",
        data=body,
        method="POST",
    )
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    context = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, context=context, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return payload.get("sessionKey")
    except Exception as exc:
        logger.error("Writer authentication failed for %s: %s", username, exc)
        raise RuntimeError("Registration writer authentication failed") from exc


def _auth_context(rest_uri, token):
    url = rest_uri.rstrip("/") + "/services/authentication/current-context?output_mode=json"
    payload = _urlopen_json(url, token=token)
    entries = payload.get("entry", [])
    if not entries:
        return {"roles": []}
    content = entries[0].get("content", {})
    roles = content.get("roles", [])
    if isinstance(roles, str):
        roles = [roles]
    capabilities = content.get("capabilities", [])
    if isinstance(capabilities, str):
        capabilities = [capabilities]
    return {
        "roles": roles,
        "capabilities": capabilities,
        "username": entries[0].get("name"),
    }


def _is_admin(rest_uri, token):
    roles = set(_auth_context(rest_uri, token).get("roles", []))
    return bool(roles & ADMIN_ROLES)


def _writer_token(request, general):
    caller = request["session"]["authtoken"]
    service = _service_token(
        request["server"]["rest_uri"],
        general.get("writer_username", ""),
    )
    return service or caller


def _kv_base(rest_uri, collection):
    return (
        rest_uri.rstrip("/")
        + f"/servicesNS/nobody/{APP}/storage/collections/data/"
        + urllib.parse.quote(collection)
    )


def _kv_base_for_app(rest_uri, app, collection):
    return (
        rest_uri.rstrip("/")
        + f"/servicesNS/nobody/{app}/storage/collections/data/"
        + urllib.parse.quote(collection)
    )


def _content_token(request):
    return request["session"]["authtoken"]


def _content_query(request, app, collection, query=None, limit=0):
    params = {
        "query": json.dumps(query or {}, separators=(",", ":")),
        "limit": str(limit),
    }
    url = (
        _kv_base_for_app(request["server"]["rest_uri"], app, collection)
        + "?"
        + urllib.parse.urlencode(params)
    )
    rows = _urlopen_json(url, token=_content_token(request))
    return rows if isinstance(rows, list) else []


def _content_save_batch(request, app, collection, documents):
    if not documents:
        return
    base = _kv_base_for_app(request["server"]["rest_uri"], app, collection)
    token = _content_token(request)
    try:
        _urlopen_json(
            base + "/batch_save",
            method="POST",
            token=token,
            data=documents,
        )
        return
    except RuntimeError as exc:
        logger.warning(
            "KV batch_save failed app=%s collection=%s; falling back to row writes: %s",
            app,
            collection,
            exc,
        )

    for document in documents:
        key = document.get("_key")
        if key:
            _urlopen_json(
                base + "/" + urllib.parse.quote(str(key), safe=""),
                method="POST",
                token=token,
                data=document,
            )
        else:
            _urlopen_json(base, method="POST", token=token, data=document)


def _content_delete_key(request, app, collection, key):
    _urlopen_json(
        _kv_base_for_app(request["server"]["rest_uri"], app, collection)
        + "/"
        + urllib.parse.quote(str(key), safe=""),
        method="DELETE",
        token=_content_token(request),
    )


def _run_export_search(request, search):
    """Run a blocking Splunk search and discard its result stream."""
    rest_uri = request["server"]["rest_uri"].rstrip("/")
    body = urllib.parse.urlencode({"search": search, "output_mode": "json"}).encode("utf-8")
    req = urllib.request.Request(
        rest_uri + "/services/search/jobs/export",
        data=body,
        method="POST",
    )
    req.add_header("Authorization", "Splunk " + request["session"]["authtoken"])
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    context = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, context=context, timeout=120) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        content = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Splunk search returned HTTP {exc.code}: {content}") from exc


def _delete_content_rows(request, app, collection, rows):
    deleted = 0
    for row in rows:
        key = row.get("_key")
        if key:
            _content_delete_key(request, app, collection, key)
            deleted += 1
    return deleted


def _dispatch_saved_search(request, app, name):
    rest_uri = request["server"]["rest_uri"].rstrip("/")
    url = (
        rest_uri
        + f"/servicesNS/nobody/{app}/saved/searches/"
        + urllib.parse.quote(name, safe="")
        + "/dispatch?output_mode=json"
    )
    req = urllib.request.Request(url, data=b"", method="POST")
    req.add_header("Authorization", "Splunk " + request["session"]["authtoken"])
    context = ssl._create_unverified_context()
    with urllib.request.urlopen(req, context=context, timeout=30) as response:
        response.read()


def _row_identity(row, fields):
    return tuple(str(row.get(field, "")) for field in fields)


def _replace_content_collection(request, ctf_id, app, collection, identity_fields, rows):
    existing = _content_query(request, app, collection, {"ctf_id": ctf_id}, limit=0)
    existing_by_identity = {}
    stale_keys = []
    for row in existing:
        identity = _row_identity(row, identity_fields)
        if identity in existing_by_identity:
            if row.get("_key"):
                stale_keys.append(row["_key"])
            continue
        existing_by_identity[identity] = row

    wanted = set()
    documents = []
    for row in rows:
        document = dict(row)
        identity = _row_identity(document, identity_fields)
        wanted.add(identity)
        old = existing_by_identity.get(identity)
        if old and old.get("_key"):
            document["_key"] = old["_key"]
        documents.append(document)

    for identity, row in existing_by_identity.items():
        if identity not in wanted and row.get("_key"):
            stale_keys.append(row["_key"])

    _content_save_batch(request, app, collection, documents)
    for key in stale_keys:
        _content_delete_key(request, app, collection, key)


def _snapshot_content(request, ctf_id):
    snapshots = {}
    for name, (app, collection, _identity_fields) in CONTENT_TARGETS.items():
        snapshots[name] = _content_query(request, app, collection, {"ctf_id": ctf_id}, limit=0)
    return snapshots


def _replace_ctf_content(request, ctf_id, content):
    for name, (app, collection, identity_fields) in CONTENT_TARGETS.items():
        _replace_content_collection(
            request,
            ctf_id,
            app,
            collection,
            identity_fields,
            content[name],
        )


def _restore_ctf_content(request, ctf_id, snapshots):
    for name, (app, collection, identity_fields) in CONTENT_TARGETS.items():
        rows = []
        for old in snapshots.get(name, []):
            row = {key: value for key, value in old.items() if key != "_key"}
            rows.append(row)
        _replace_content_collection(request, ctf_id, app, collection, identity_fields, rows)


def _kv_query(request, general, collection, query=None, limit=0, sort=None):
    token = _writer_token(request, general)
    params = {
        "query": json.dumps(query or {}, separators=(",", ":")),
        "limit": str(limit),
    }
    if sort:
        params["sort"] = json.dumps(sort, separators=(",", ":"))
    url = _kv_base(request["server"]["rest_uri"], collection) + "?" + urllib.parse.urlencode(params)
    rows = _urlopen_json(url, token=token)
    return rows if isinstance(rows, list) else []


def _kv_insert(request, general, collection, document):
    token = _writer_token(request, general)
    return _urlopen_json(
        _kv_base(request["server"]["rest_uri"], collection),
        method="POST",
        token=token,
        data=document,
    )


def _kv_update(request, general, collection, key, document):
    token = _writer_token(request, general)
    return _urlopen_json(
        _kv_base(request["server"]["rest_uri"], collection) + "/" + urllib.parse.quote(key),
        method="POST",
        token=token,
        data=document,
    )


def _event_by_id(request, general, ctf_id):
    rows = _kv_query(request, general, EVENTS_COLLECTION, {"ctf_id": ctf_id}, limit=1)
    return rows[0] if rows else None


def _registration_by_user(request, general, ctf_id, username):
    rows = _kv_query(
        request,
        general,
        REGISTRATIONS_COLLECTION,
        {"ctf_id": ctf_id, "Username": username},
        limit=1,
    )
    return rows[0] if rows else None


def _upsert_registration(request, general, document):
    existing = _registration_by_user(
        request,
        general,
        document["ctf_id"],
        document["Username"],
    )
    if existing and existing.get("_key"):
        document["_key"] = existing["_key"]
        _kv_update(
            request,
            general,
            REGISTRATIONS_COLLECTION,
            existing["_key"],
            document,
        )
        return "updated"
    _kv_insert(request, general, REGISTRATIONS_COLLECTION, document)
    return "created"


def _upsert_event(request, general, document):
    existing = _event_by_id(request, general, document["ctf_id"])
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if existing and existing.get("_key"):
        document["_key"] = existing["_key"]
        document["created_at"] = existing.get("created_at", now)
        document["updated_at"] = now
        _kv_update(request, general, EVENTS_COLLECTION, existing["_key"], document)
        return "updated"
    document["created_at"] = now
    document["updated_at"] = now
    _kv_insert(request, general, EVENTS_COLLECTION, document)
    return "created"


def _user_endpoint(rest_uri, username):
    return rest_uri.rstrip("/") + "/services/authentication/users/" + urllib.parse.quote(username, safe="")


def _get_user_roles(request, general, username):
    token = _writer_token(request, general)
    url = _user_endpoint(request["server"]["rest_uri"], username) + "?output_mode=json"
    payload = _urlopen_json(url, token=token)
    entries = payload.get("entry", []) if isinstance(payload, dict) else []
    if not entries:
        raise RuntimeError(f"Splunk user not found: {username}")
    roles = entries[0].get("content", {}).get("roles", [])
    if isinstance(roles, str):
        roles = [roles]
    return [str(role) for role in roles]


def _ensure_participant_roles(request, general, username, required_roles):
    required = parse_roles(required_roles)
    current = _get_user_roles(request, general, username)
    missing = [role for role in required if role not in current]
    if not missing:
        return {"required": required, "added": [], "roles": current}

    merged = list(current)
    for role in missing:
        if role not in merged:
            merged.append(role)

    pairs = [("roles", role) for role in merged]
    pairs.append(("output_mode", "json"))
    body = urllib.parse.urlencode(pairs).encode("utf-8")
    token = _writer_token(request, general)
    _urlopen_json(
        _user_endpoint(request["server"]["rest_uri"], username),
        method="POST",
        token=token,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    logger.info("Assigned CTF role(s) user=%s roles=%s", username, ",".join(missing))
    return {"required": required, "added": missing, "roles": merged}


def _public_event(event, registration=None):
    reg_state = registration_state(event)
    evt_state = event_state(event)
    return {
        "ctf_id": event.get("ctf_id", ""),
        "name": event.get("name", ""),
        "short_description": event.get("short_description", ""),
        "description": event.get("description", ""),
        "image_url": event.get("image_url", ""),
        "registration_opens": event.get("registration_opens", ""),
        "registration_closes": event.get("registration_closes", ""),
        "event_starts": event.get("event_starts", ""),
        "event_ends": event.get("event_ends", ""),
        "search_url": event.get("search_url", ""),
        "search_url_desc": event.get("search_url_desc", ""),
        "scoring_url": event.get("scoring_url", ""),
        "participant_roles": parse_roles(event.get("participant_roles", "")),
        "enabled": parse_bool(event.get("enabled"), False),
        "allow_updates": parse_bool(event.get("allow_updates"), True),
        "registration_state": reg_state,
        "event_state": evt_state,
        "registered": bool(registration),
        "registration": registration or {},
    }


class RegistrationHandler(PersistentServerConnectionApplication):
    def __init__(self, command_line, command_arg):
        PersistentServerConnectionApplication.__init__(self)

    def handle(self, in_string):
        try:
            request = json.loads(in_string.decode("utf-8") if isinstance(in_string, bytes) else in_string)
            return self._route(request)
        except ValueError as exc:
            logger.info("Validation error: %s", exc)
            return _json_response({"message": str(exc)}, 400)
        except PermissionError as exc:
            logger.warning("Permission error: %s", exc)
            return _json_response({"message": str(exc)}, 403)
        except Exception as exc:
            logger.exception("Unhandled registration error")
            return _json_response({"message": str(exc)}, 500)

    def _route(self, request):
        if not request.get("session", {}).get("user") or not request.get("session", {}).get("authtoken"):
            raise PermissionError("Authentication is required")

        path = (request.get("path_info") or "").strip("/")
        method = (request.get("method") or "GET").upper()

        if path == "events" and method == "GET":
            return _json_response(self._events(request))
        if path == "register" and method == "POST":
            return _json_response(self._register(request))

        if path == "admin/events" and method == "GET":
            self._require_admin(request)
            return _json_response(self._admin_events(request))
        if path == "admin/event" and method == "POST":
            self._require_admin(request)
            return _json_response(self._admin_save_event(request))
        if path == "admin/roster" and method == "GET":
            self._require_admin(request)
            return _json_response(self._admin_roster(request))
        if path == "admin/reset-run" and method == "POST":
            self._require_admin(request)
            return _json_response(self._admin_reset_run(request))

        return _json_response({"message": "Not found"}, 404)

    def _require_admin(self, request):
        if not _is_admin(request["server"]["rest_uri"], request["session"]["authtoken"]):
            raise PermissionError("CTF registration administrator role is required")

    def _require_content_admin(self, request):
        roles = set(
            _auth_context(
                request["server"]["rest_uri"],
                request["session"]["authtoken"],
            ).get("roles", [])
        )
        if not roles.intersection(CONTENT_ADMIN_ROLES):
            raise PermissionError("admin or ctf_admin role is required to import protected CTF content")

    def _require_reset_admin(self, request):
        context = _auth_context(
            request["server"]["rest_uri"],
            request["session"]["authtoken"],
        )
        roles = set(context.get("roles", []))
        capabilities = set(context.get("capabilities", []))
        if "admin" not in roles:
            raise PermissionError("Splunk admin role is required to reset a CTF run")
        if "delete_by_keyword" not in capabilities:
            raise PermissionError(
                "Resetting score events requires the delete_by_keyword capability; "
                "temporarily assign the built-in can_delete role to the administrator performing the reset"
            )

    def _events(self, request):
        general = _load_general()
        username = request["session"]["user"]
        events = _kv_query(request, general, EVENTS_COLLECTION, {}, limit=0)
        result = []

        for event in events:
            try:
                evt_state = event_state(event)
                if evt_state == "COMPLETED":
                    continue
                registration = _registration_by_user(
                    request,
                    general,
                    event.get("ctf_id", ""),
                    username,
                )
                result.append(_public_event(event, registration))
            except ValueError as exc:
                logger.warning("Skipping invalid event %s: %s", event.get("ctf_id"), exc)

        result.sort(key=lambda row: (row.get("event_starts", ""), row.get("name", "").lower()))
        return {"username": username, "events": result}

    def _register(self, request):
        general = _load_general()
        values = _pairs_to_dict(request.get("form"))
        ctf_id = values.get("ctf_id", "").strip().lower()
        if not ctf_id:
            raise ValueError("ctf_id is required")

        event = _event_by_id(request, general, ctf_id)
        if not event:
            raise ValueError("CTF event was not found")

        state = registration_state(event)
        if state != "OPEN":
            raise PermissionError(f"Registration is not open for this CTF (state: {state})")

        clean = validate_registration(values)
        username = request["session"]["user"]
        existing = _registration_by_user(request, general, ctf_id, username)
        if existing and not parse_bool(event.get("allow_updates"), True):
            raise PermissionError("Registration updates are disabled for this CTF")

        role_result = _ensure_participant_roles(
            request,
            general,
            username,
            event.get("participant_roles", general.get("default_participant_roles", "ctf_competitor")),
        )

        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        doc = dict(existing or {})
        doc.update(clean)
        doc.update({
            "ctf_id": ctf_id,
            "Username": username,
            "SearchUrl": event.get("search_url", ""),
            "SearchUrlDesc": event.get("search_url_desc", ""),
            "ScoringUrl": event.get("scoring_url", ""),
            "status": "registered",
            "registered_at": existing.get("registered_at", now) if existing else now,
            "updated_at": now,
        })

        result = _upsert_registration(request, general, doc)
        logger.info(
            "Registration %s user=%s ctf_id=%s team=%s",
            result,
            username,
            ctf_id,
            doc.get("Team"),
        )
        return {
            "message": "Registration saved successfully.",
            "result": result,
            "roles_added": role_result["added"],
            "required_roles": role_result["required"],
        }

    def _admin_events(self, request):
        general = _load_general()
        events = _kv_query(request, general, EVENTS_COLLECTION, {}, limit=0)
        output = []
        for event in events:
            safe = dict(event)
            try:
                safe["registration_state"] = registration_state(event)
                safe["event_state"] = event_state(event)
            except ValueError as exc:
                safe["registration_state"] = "INVALID"
                safe["event_state"] = "INVALID"
                safe["validation_error"] = str(exc)
            output.append(safe)
        output.sort(key=lambda row: (row.get("event_starts", ""), row.get("name", "").lower()))
        return {"events": output}

    def _admin_save_event(self, request):
        general = _load_general()
        values = _pairs_to_dict(request.get("form"))
        allowed_roles = parse_roles(general.get("allowed_participant_roles", "ctf_competitor"))
        if not values.get("participant_roles"):
            values["participant_roles"] = general.get("default_participant_roles", "ctf_competitor")

        event = validate_event(values, allowed_roles=allowed_roles)

        content_fields = ("questions_csv", "answers_csv", "hints_csv")
        supplied = [bool(values.get(field, "").strip()) for field in content_fields]
        content = None
        snapshots = None
        existing_event = _event_by_id(request, general, event["ctf_id"])

        if any(supplied):
            if not all(supplied):
                raise ValueError("Questions, answers, and hints CSV files must all be supplied together")
            self._require_content_admin(request)
            content = parse_ctf_content(
                event["ctf_id"],
                values["questions_csv"],
                values["answers_csv"],
                values["hints_csv"],
                event_starts=event["event_starts"],
                event_ends=event["event_ends"],
                use_event_window=parse_bool(values.get("use_event_window"), True),
            )
            # This is also a permission/app-availability preflight before the event is changed.
            snapshots = _snapshot_content(request, event["ctf_id"])

        result = _upsert_event(request, general, event)
        try:
            if content is not None:
                _replace_ctf_content(request, event["ctf_id"], content)
        except Exception:
            logger.exception("Content import failed; rolling back ctf_id=%s", event["ctf_id"])
            try:
                if snapshots is not None:
                    _restore_ctf_content(request, event["ctf_id"], snapshots)
                if existing_event and existing_event.get("_key"):
                    _kv_update(
                        request,
                        general,
                        EVENTS_COLLECTION,
                        existing_event["_key"],
                        existing_event,
                    )
                else:
                    created = _event_by_id(request, general, event["ctf_id"])
                    if created and created.get("_key"):
                        token = _writer_token(request, general)
                        _urlopen_json(
                            _kv_base(request["server"]["rest_uri"], EVENTS_COLLECTION)
                            + "/"
                            + urllib.parse.quote(str(created["_key"]), safe=""),
                            method="DELETE",
                            token=token,
                        )
            except Exception:
                logger.exception("Rollback failed for ctf_id=%s", event["ctf_id"])
            raise

        logger.info(
            "CTF event %s by=%s ctf_id=%s content=%s",
            result,
            request["session"]["user"],
            event["ctf_id"],
            content["counts"] if content else "unchanged",
        )
        response = {
            "message": "CTF event saved.",
            "result": result,
            "ctf_id": event["ctf_id"],
        }
        if content is not None:
            response["content"] = content["counts"]
            response["message"] = (
                "CTF event and content saved: "
                f"{content['counts']['questions']} questions, "
                f"{content['counts']['answers']} answers, "
                f"{content['counts']['hints']} hints."
            )
        return response

    def _admin_reset_run(self, request):
        self._require_reset_admin(request)
        general = _load_general()
        values = _pairs_to_dict(request.get("form"))
        ctf_id = values.get("ctf_id", "").strip().lower()
        confirm = values.get("confirm_ctf_id", "").strip().lower()
        if not ctf_id or confirm != ctf_id:
            raise ValueError("Reset confirmation must exactly match ctf_id")

        event = _event_by_id(request, general, ctf_id)
        if not event:
            raise ValueError("CTF event was not found")

        # Preflight the KV Store reads before deleting any indexed score events.
        registrations = _kv_query(
            request, general, REGISTRATIONS_COLLECTION, {"ctf_id": ctf_id}, limit=0
        )
        hint_entitlements = _content_query(
            request, SCOREBOARD_APP, "ctf_hint_entitlements", {"ctf_id": ctf_id}, limit=0
        )

        # Splunk's delete command marks matching events as deleted from search.
        # It does not immediately reclaim index disk space, which is fine for
        # resetting a reusable CTF while retaining content and the event definition.
        for index in ("scoreboard", "scoreboard_admin"):
            _run_export_search(
                request,
                f'search index={index} ctf_id="{ctf_id}" | delete',
            )

        registration_deleted = 0
        token = _writer_token(request, general)
        for row in registrations:
            key = row.get("_key")
            if not key:
                continue
            _urlopen_json(
                _kv_base(request["server"]["rest_uri"], REGISTRATIONS_COLLECTION)
                + "/"
                + urllib.parse.quote(str(key), safe=""),
                method="DELETE",
                token=token,
            )
            registration_deleted += 1

        hints_deleted = _delete_content_rows(
            request, SCOREBOARD_APP, "ctf_hint_entitlements", hint_entitlements
        )

        try:
            _dispatch_saved_search(
                request, SCOREBOARD_ADMIN_APP, "Generate Latest Scores and Ranks"
            )
        except Exception as exc:
            # Score events are already reset; a stale cached rank lookup is less
            # important than failing the entire reset. The next scheduled run
            # will rebuild currentscore.csv from the now-clean scoreboard index.
            logger.warning("Unable to refresh currentscore.csv after reset: %s", exc)

        logger.warning(
            "CTF run reset by=%s ctf_id=%s registrations=%s hint_entitlements=%s",
            request["session"]["user"],
            ctf_id,
            registration_deleted,
            hints_deleted,
        )
        return {
            "message": (
                f"Reset {ctf_id}: score events hidden, "
                f"{registration_deleted} registrations removed, "
                f"{hints_deleted} hint entitlements removed. "
                "Questions, answers, hints, and the CTF event were preserved."
            ),
            "ctf_id": ctf_id,
            "registrations_deleted": registration_deleted,
            "hint_entitlements_deleted": hints_deleted,
        }

    def _admin_roster(self, request):
        general = _load_general()
        query = _pairs_to_dict(request.get("query"))
        ctf_id = query.get("ctf_id", "").strip().lower()
        if not ctf_id:
            raise ValueError("ctf_id is required")

        event = _event_by_id(request, general, ctf_id)
        if not event:
            raise ValueError("CTF event was not found")

        users = _kv_query(
            request,
            general,
            REGISTRATIONS_COLLECTION,
            {"ctf_id": ctf_id},
            limit=0,
        )
        users.sort(key=lambda x: (str(x.get("Team", "")).lower(), str(x.get("Username", "")).lower()))
        teams = len({row.get("Team") for row in users if row.get("Team")})

        safe = []
        for row in users:
            safe.append({
                k: row.get(k, "")
                for k in (
                    "Username",
                    "DisplayUsername",
                    "Team",
                    "Email",
                    "FirstName",
                    "LastName",
                    "status",
                    "registered_at",
                    "updated_at",
                )
            })
        return {
            "count": len(safe),
            "teams": teams,
            "ctf_id": ctf_id,
            "event": event.get("name", ctf_id),
            "users": safe,
        }
