import os
import sys
import unittest
from datetime import datetime, timezone

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "bin")))

from registration_core import (
    event_state,
    parse_iso8601,
    parse_roles,
    registration_state,
    validate_event,
    validate_registration,
)


class RegistrationCoreTests(unittest.TestCase):
    def event(self):
        return {
            "enabled": "true",
            "registration_opens": "2026-10-01T12:00:00Z",
            "registration_closes": "2026-10-05T12:00:00Z",
            "event_starts": "2026-10-10T12:00:00Z",
            "event_ends": "2026-10-12T12:00:00Z",
        }

    def test_registration_state_boundaries(self):
        cfg = self.event()
        self.assertEqual(registration_state(cfg, datetime(2026, 9, 30, tzinfo=timezone.utc)), "UPCOMING")
        self.assertEqual(registration_state(cfg, datetime(2026, 10, 2, tzinfo=timezone.utc)), "OPEN")
        self.assertEqual(registration_state(cfg, datetime(2026, 10, 6, tzinfo=timezone.utc)), "CLOSED")

    def test_disabled_registration(self):
        cfg = self.event()
        cfg["enabled"] = "false"
        self.assertEqual(registration_state(cfg), "DISABLED")

    def test_event_state(self):
        cfg = self.event()
        self.assertEqual(event_state(cfg, datetime(2026, 10, 9, tzinfo=timezone.utc)), "UPCOMING")
        self.assertEqual(event_state(cfg, datetime(2026, 10, 11, tzinfo=timezone.utc)), "IN_PROGRESS")
        self.assertEqual(event_state(cfg, datetime(2026, 10, 13, tzinfo=timezone.utc)), "COMPLETED")

    def test_timezone_required(self):
        with self.assertRaises(ValueError):
            parse_iso8601("2026-10-01T12:00:00")

    def test_registration_validation(self):
        result = validate_registration({
            "display_name": "Player 1",
            "team": "Blue",
            "email": "p@example.com",
        })
        self.assertEqual(result["DisplayUsername"], "Player 1")
        self.assertEqual(result["Team"], "Blue")

    def test_invalid_email(self):
        with self.assertRaises(ValueError):
            validate_registration({
                "display_name": "Player 1",
                "team": "Blue",
                "email": "bad",
            })

    def test_parse_roles(self):
        self.assertEqual(
            parse_roles("ctf_competitor;extra_role,another-role"),
            ["ctf_competitor", "extra_role", "another-role"],
        )

    def test_validate_event(self):
        values = {
            "ctf_id": "asteron-easy-2026",
            "name": "Asteron Easy",
            "short_description": "Easy Asteron challenge",
            "description": "Longer description",
            "image_url": "/static/app/SA-ctf_registration/images/asteron.png",
            "registration_opens": "2026-10-01T12:00:00Z",
            "registration_closes": "2026-10-05T12:00:00Z",
            "event_starts": "2026-10-10T12:00:00Z",
            "event_ends": "2026-10-12T12:00:00Z",
            "search_url": "http://192.168.1.250:8000",
            "participant_roles": "ctf_competitor",
            "enabled": "true",
            "allow_updates": "true",
        }
        event = validate_event(values, allowed_roles=["ctf_competitor"])
        self.assertEqual(event["ctf_id"], "asteron-easy-2026")

    def test_disallowed_event_role(self):
        values = {
            "ctf_id": "asteron-easy-2026",
            "name": "Asteron Easy",
            "short_description": "Easy Asteron challenge",
            "description": "Longer description",
            "registration_opens": "2026-10-01T12:00:00Z",
            "registration_closes": "2026-10-05T12:00:00Z",
            "event_starts": "2026-10-10T12:00:00Z",
            "event_ends": "2026-10-12T12:00:00Z",
            "search_url": "http://192.168.1.250:8000",
            "participant_roles": "ctf_admin",
            "enabled": "true",
            "allow_updates": "true",
        }
        with self.assertRaises(ValueError):
            validate_event(values, allowed_roles=["ctf_competitor"])


if __name__ == "__main__":
    unittest.main()
