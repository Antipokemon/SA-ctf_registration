from __future__ import annotations

import re
from datetime import datetime, timezone

CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


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


def registration_state(config, now=None):
    now = now or datetime.now(timezone.utc)
    if not parse_bool(config.get("enabled"), False):
        return "DISABLED"
    opens = parse_iso8601(config.get("opens_at"))
    closes = parse_iso8601(config.get("closes_at"))
    if closes <= opens:
        raise ValueError("closes_at must be later than opens_at")
    if now < opens:
        return "UPCOMING"
    if now > closes:
        return "CLOSED"
    return "OPEN"


def clean_text(value, field, max_len, required=False):
    text = (value or "").strip()
    if required and not text:
        raise ValueError(f"{field} is required")
    if len(text) > max_len:
        raise ValueError(f"{field} must be {max_len} characters or fewer")
    if CONTROL_RE.search(text):
        raise ValueError(f"{field} contains invalid control characters")
    return text


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
