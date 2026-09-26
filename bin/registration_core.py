from __future__ import annotations

import re
from datetime import datetime, timezone

CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
ROLE_RE = re.compile(r"^[a-z0-9_-]+$")
CTF_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


def parse_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def parse_iso8601(value):
    if not value:
        raise ValueError("timestamp is required")
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError("timestamp must include a timezone (use Z for UTC)")
    return dt.astimezone(timezone.utc)


def parse_roles(value):
    text = str(value or "").strip()
    if not text:
        return []
    parts = re.split(r"[;,]", text)
    roles = []
    for part in parts:
        role = part.strip()
        if not role:
            continue
        if not ROLE_RE.fullmatch(role):
            raise ValueError(f"Invalid Splunk role name: {role}")
        if role not in roles:
            roles.append(role)
    return roles


def clean_text(value, field, max_len, required=False):
    text = (value or "").strip()
    if required and not text:
        raise ValueError(f"{field} is required")
    if len(text) > max_len:
        raise ValueError(f"{field} must be {max_len} characters or fewer")
    if CONTROL_RE.search(text):
        raise ValueError(f"{field} contains invalid control characters")
    return text


def registration_state(event, now=None):
    now = now or datetime.now(timezone.utc)
    if not parse_bool(event.get("enabled"), False):
        return "DISABLED"
    opens = parse_iso8601(event.get("registration_opens"))
    closes = parse_iso8601(event.get("registration_closes"))
    if closes <= opens:
        raise ValueError("registration_closes must be later than registration_opens")
    if now < opens:
        return "UPCOMING"
    if now > closes:
        return "CLOSED"
    return "OPEN"


def event_state(event, now=None):
    now = now or datetime.now(timezone.utc)
    starts = parse_iso8601(event.get("event_starts"))
    ends = parse_iso8601(event.get("event_ends"))
    if ends <= starts:
        raise ValueError("event_ends must be later than event_starts")
    if now < starts:
        return "UPCOMING"
    if now > ends:
        return "COMPLETED"
    return "IN_PROGRESS"


def validate_event(values, allowed_roles=None):
    ctf_id = clean_text(values.get("ctf_id"), "CTF ID", 64, True).lower()
    if not CTF_ID_RE.fullmatch(ctf_id):
        raise ValueError("CTF ID must use lowercase letters, numbers, hyphens, or underscores")

    result = {
        "ctf_id": ctf_id,
        "name": clean_text(values.get("name"), "Name", 120, True),
        "short_description": clean_text(values.get("short_description"), "Short description", 280, True),
        "description": clean_text(values.get("description"), "Description", 6000, True),
        "image_url": clean_text(values.get("image_url"), "Image URL", 1000),
        "registration_opens": clean_text(values.get("registration_opens"), "Registration opens", 64, True),
        "registration_closes": clean_text(values.get("registration_closes"), "Registration closes", 64, True),
        "event_starts": clean_text(values.get("event_starts"), "Event starts", 64, True),
        "event_ends": clean_text(values.get("event_ends"), "Event ends", 64, True),
        "search_url": clean_text(values.get("search_url"), "Search URL", 1000, True),
        "search_url_desc": clean_text(values.get("search_url_desc"), "Search URL description", 120),
        "scoring_url": clean_text(values.get("scoring_url"), "Scoring URL", 1000),
        "participant_roles": ",".join(parse_roles(values.get("participant_roles"))),
        "enabled": "true" if parse_bool(values.get("enabled"), False) else "false",
        "allow_updates": "true" if parse_bool(values.get("allow_updates"), True) else "false",
    }

    reg_open = parse_iso8601(result["registration_opens"])
    reg_close = parse_iso8601(result["registration_closes"])
    event_start = parse_iso8601(result["event_starts"])
    event_end = parse_iso8601(result["event_ends"])

    if reg_close <= reg_open:
        raise ValueError("Registration closes must be later than registration opens")
    if event_end <= event_start:
        raise ValueError("Event ends must be later than event starts")
    if reg_open >= event_end:
        raise ValueError("Registration must open before the event ends")

    roles = parse_roles(result["participant_roles"])
    if not roles:
        raise ValueError("At least one participant role is required")

    if allowed_roles is not None:
        allowed = set(allowed_roles)
        denied = [role for role in roles if role not in allowed]
        if denied:
            raise ValueError("Role(s) are not allowed for registration: " + ", ".join(denied))

    return result


def validate_registration(values):
    result = {
        "DisplayUsername": clean_text(values.get("display_name"), "Display name", 80, True),
        "Team": clean_text(values.get("team"), "Team name", 80, True),
        "FirstName": clean_text(values.get("first_name"), "First name", 80),
        "LastName": clean_text(values.get("last_name"), "Last name", 80),
        "Email": clean_text(values.get("email"), "Email", 254),
    }
    if result["Email"] and not EMAIL_RE.match(result["Email"]):
        raise ValueError("Email address is not valid")
    return result
