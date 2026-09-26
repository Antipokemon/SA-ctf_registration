import os
import sys
import unittest
from datetime import datetime, timezone

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "bin")))

from registration_core import parse_iso8601, registration_state, validate_registration


class RegistrationCoreTests(unittest.TestCase):
    def test_state_disabled(self):
        cfg = {"enabled": "false", "opens_at": "2026-10-01T12:00:00Z", "closes_at": "2026-10-05T12:00:00Z"}
        self.assertEqual(registration_state(cfg), "DISABLED")

    def test_state_boundaries(self):
        cfg = {"enabled": "true", "opens_at": "2026-10-01T12:00:00Z", "closes_at": "2026-10-05T12:00:00Z"}
        self.assertEqual(registration_state(cfg, datetime(2026, 9, 30, tzinfo=timezone.utc)), "UPCOMING")
        self.assertEqual(registration_state(cfg, datetime(2026, 10, 2, tzinfo=timezone.utc)), "OPEN")
        self.assertEqual(registration_state(cfg, datetime(2026, 10, 6, tzinfo=timezone.utc)), "CLOSED")

    def test_timezone_required(self):
        with self.assertRaises(ValueError):
            parse_iso8601("2026-10-01T12:00:00")

    def test_registration_validation(self):
        result = validate_registration({"display_name": "Player 1", "team": "Blue", "email": "p@example.com"})
        self.assertEqual(result["DisplayUsername"], "Player 1")
        self.assertEqual(result["Team"], "Blue")

    def test_invalid_email(self):
        with self.assertRaises(ValueError):
            validate_registration({"display_name": "Player 1", "team": "Blue", "email": "bad"})


if __name__ == "__main__":
    unittest.main()
