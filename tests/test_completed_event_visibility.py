from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CompletedEventVisibilityTests(unittest.TestCase):
    def test_events_endpoint_can_return_registered_completed_events(self):
        text = (ROOT / "bin" / "registration_rest.py").read_text(encoding="utf-8")
        self.assertIn('query = _pairs_to_dict(request.get("query"))', text)
        self.assertIn('include_completed = parse_bool(query.get("include_completed"), False)', text)
        self.assertIn('evt_state == "COMPLETED" and not (include_completed and registration)', text)

    def test_completed_events_remain_hidden_by_default(self):
        text = (ROOT / "bin" / "registration_rest.py").read_text(encoding="utf-8")
        self.assertIn('include_completed = parse_bool(query.get("include_completed"), False)', text)
        self.assertIn('not (include_completed and registration)', text)


if __name__ == "__main__":
    unittest.main()
