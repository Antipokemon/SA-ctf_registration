from __future__ import annotations

import configparser
import json
import logging
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from splunk.persistconn.application import PersistentServerConnectionApplication

APP = "SA-ctf_registration"
BASE = Path(os.environ.get("SPLUNK_HOME", "/opt/splunk")) / "etc" / "apps" / APP
BIN = BASE / "bin"
import sys
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

from registration_core import parse_bool, parse_iso8601, registration_state, validate_registration

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


def _load_config():
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str.lower
    parser.read([str(DEFAULT_CONFIG), str(LOCAL_CONFIG)])
    if not parser.has_section("registration"):
        raise RuntimeError("Missing [registration] configuration")
    return dict(parser.items("registration"))


def _load_secret():
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(str(SECRETS_CONFIG))
    if parser.has_section("writer"):
        return parser.get("writer", "password", fallback="").strip()
    return ""


def _save_config(values):
    LOCAL_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    current = _load_config()
    allowed = {
        "enabled", "opens_at", "closes_at", "event", "search_url",
        "search_url_desc", "scoring_url", "allow_updates", "scoreboard_app",
        "users_collection", "writer_username"
    }
    for key, value in values.items():
        if key in allowed:
            current[key] = str(value)

    parser = configparser.ConfigParser(interpolation=None)
    parser["registration"] = current
    tmp = LOCAL_CONFIG.with_suffix(".conf.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        parser.write(fh)
    os.chmod(tmp, 0o600)
    os.replace(tmp, LOCAL_CONFIG)


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
    body = urllib.parse.urlencode({"username": username, "password": password, "output_mode": "json"}).encode("utf-8")
    req = urllib.request.Request(rest_uri.rstrip("/") + "/services/auth/login", data=body, method="POST")
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
    return {"roles": content.get("roles", []), "username": entries[0].get("name")}


def _is_admin(rest_uri, token):
    roles = set(_auth_context(rest_uri, token).get("roles", []))
    return bool(roles & ADMIN_ROLES)


def _kv_base(rest_uri, config):
    app = config.get("scoreboard_app", "SA-ctf_scoreboard")
    collection = config.get("users_collection", "ctf_users")
    return rest_uri.rstrip("/") + f"/servicesNS/nobody/{urllib.parse.quote(app)}/storage/collections/data/{urllib.parse.quote(collection)}"


def _writer_token(request, config):
    caller = request["session"]["authtoken"]
    service = _service_token(request["server"]["rest_uri"], config.get("writer_username", ""))
    return service or caller


def _find_user(request, config, username):
    token = _writer_token(request, config)
    query = json.dumps({"Username": username}, separators=(",", ":"))
    url = _kv_base(request["server"]["rest_uri"], config) + "?" + urllib.parse.urlencode({"query": query, "limit": 1})
    rows = _urlopen_json(url, token=token)
    return rows[0] if isinstance(rows, list) and rows else None


def _upsert_user(request, config, document):
    token = _writer_token(request, config)
    existing = _find_user(request, config, document["Username"])
    base = _kv_base(request["server"]["rest_uri"], config)
    if existing and existing.get("_key"):
        document["_key"] = existing["_key"]
        url = base + "/" + urllib.parse.quote(existing["_key"])
        _urlopen_json(url, method="POST", token=token, data=document)
        return "updated"
    _urlopen_json(base, method="POST", token=token, data=document)
    return "created"


def _roster(request, config):
    token = _writer_token(request, config)
    event = config.get("event", "")
    query = json.dumps({"Event": event}, separators=(",", ":")) if event else "{}"
    url = _kv_base(request["server"]["rest_uri"], config) + "?" + urllib.parse.urlencode({"query": query, "limit": 0})
    rows = _urlopen_json(url, token=token)
    if not isinstance(rows, list):
        return []
    return sorted(rows, key=lambda x: (str(x.get("Team", "")).lower(), str(x.get("Username", "")).lower()))


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
        if path == "status" and method == "GET":
            return _json_response(self._status(request))
        if path == "register" and method == "POST":
            return _json_response(self._register(request))
        if path == "admin/config" and method == "GET":
            self._require_admin(request)
            return _json_response(self._admin_config(request))
        if path == "admin/config" and method == "POST":
            self._require_admin(request)
            return _json_response(self._admin_save(request))
        if path == "admin/roster" and method == "GET":
            self._require_admin(request)
            return _json_response(self._admin_roster(request))
        return _json_response({"message": "Not found"}, 404)

    def _require_admin(self, request):
        if not _is_admin(request["server"]["rest_uri"], request["session"]["authtoken"]):
            raise PermissionError("CTF registration administrator role is required")

    def _status(self, request):
        config = _load_config()
        state = registration_state(config)
        username = request["session"]["user"]
        record = _find_user(request, config, username)
        registered = bool(record)
        allow_updates = parse_bool(config.get("allow_updates"), True)
        can_register = state == "OPEN" and (not registered or allow_updates)
        return {
            "state": state,
            "enabled": parse_bool(config.get("enabled")),
            "event": config.get("event", ""),
            "opens_at": config.get("opens_at", ""),
            "closes_at": config.get("closes_at", ""),
            "username": username,
            "registered": registered,
            "can_register": can_register,
            "registration": record or {},
        }

    def _register(self, request):
        config = _load_config()
        state = registration_state(config)
        if state != "OPEN":
            raise PermissionError(f"Registration is not open (state: {state})")
        values = _pairs_to_dict(request.get("form"))
        clean = validate_registration(values)
        username = request["session"]["user"]
        existing = _find_user(request, config, username)
        if existing and not parse_bool(config.get("allow_updates"), True):
            raise PermissionError("Registration updates are disabled")

        doc = dict(existing or {})
        doc.update(clean)
        doc.update({
            "Username": username,
            "SearchUrl": config.get("search_url", ""),
            "SearchUrlDesc": config.get("search_url_desc", ""),
            "SearchUrl2": doc.get("SearchUrl2", ""),
            "SearchUrl2Desc": doc.get("SearchUrl2Desc", ""),
            "SearchUrl3": doc.get("SearchUrl3", ""),
            "SearchUrl3Desc": doc.get("SearchUrl3Desc", ""),
            "SearchUrl4": doc.get("SearchUrl4", ""),
            "SearchUrl4Desc": doc.get("SearchUrl4Desc", ""),
            "ScoringUrl": config.get("scoring_url", ""),
            "Event": config.get("event", ""),
            "RegistrationUpdated": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        })
        result = _upsert_user(request, config, doc)
        logger.info("Registration %s user=%s event=%s team=%s", result, username, doc.get("Event"), doc.get("Team"))
        return {"message": "Registration saved successfully.", "result": result}

    def _admin_config(self, request):
        config = _load_config()
        return {
            "state": registration_state(config),
            "enabled": parse_bool(config.get("enabled")),
            "opens_at": config.get("opens_at", ""),
            "closes_at": config.get("closes_at", ""),
            "event": config.get("event", ""),
            "search_url": config.get("search_url", ""),
            "search_url_desc": config.get("search_url_desc", ""),
            "scoring_url": config.get("scoring_url", ""),
            "allow_updates": parse_bool(config.get("allow_updates"), True),
        }

    def _admin_save(self, request):
        values = _pairs_to_dict(request.get("form"))
        candidate = _load_config()
        for field in ("enabled", "opens_at", "closes_at", "event", "search_url", "search_url_desc", "scoring_url", "allow_updates"):
            if field in values:
                candidate[field] = values[field]
        parse_iso8601(candidate.get("opens_at"))
        parse_iso8601(candidate.get("closes_at"))
        if parse_iso8601(candidate["closes_at"]) <= parse_iso8601(candidate["opens_at"]):
            raise ValueError("Closes at must be later than opens at")
        if not candidate.get("event", "").strip():
            raise ValueError("Event is required")
        if not candidate.get("search_url", "").strip():
            raise ValueError("Search URL is required")
        _save_config(candidate)
        logger.info("Registration configuration updated by %s", request["session"]["user"])
        return {"message": "Registration configuration saved.", "state": registration_state(candidate)}

    def _admin_roster(self, request):
        config = _load_config()
        users = _roster(request, config)
        teams = len({row.get("Team") for row in users if row.get("Team")})
        safe = []
        for row in users:
            safe.append({k: row.get(k, "") for k in ("Username", "DisplayUsername", "Team", "Email", "FirstName", "LastName", "Event")})
        return {"count": len(safe), "teams": teams, "event": config.get("event", ""), "users": safe}
