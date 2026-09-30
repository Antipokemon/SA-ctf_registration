import os
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


class RegistrationContentUiTests(unittest.TestCase):
    def test_admin_view_has_three_content_uploads(self):
        xml = (ROOT / "default" / "data" / "ui" / "views" / "admin.xml").read_text()
        self.assertIn('id="ctfr-questions-csv"', xml)
        self.assertIn('id="ctfr-answers-csv"', xml)
        self.assertIn('id="ctfr-hints-csv"', xml)
        self.assertIn('id="ctfr-use-event-window"', xml)

    def test_javascript_submits_content_fields(self):
        js = (ROOT / "appserver" / "static" / "registration_admin.js").read_text()
        self.assertIn("payload.questions_csv", js)
        self.assertIn("payload.answers_csv", js)
        self.assertIn("payload.hints_csv", js)
        self.assertIn("use_event_window", js)

    def test_backend_targets_expected_apps_and_collections(self):
        py = (ROOT / "bin" / "registration_rest.py").read_text()
        self.assertIn('SCOREBOARD_APP = "SA-ctf_scoreboard"', py)
        self.assertIn('SCOREBOARD_ADMIN_APP = "SA-ctf_scoreboard_admin"', py)
        self.assertIn('"questions": (SCOREBOARD_ADMIN_APP, "ctf_questions"', py)
        self.assertIn('"ctf_questions"', py)
        self.assertIn('"ctf_answers"', py)
        self.assertIn('"ctf_hints"', py)
        self.assertIn('def _verify_ctf_content(', py)
        self.assertIn('_verify_ctf_content(request, event["ctf_id"], content)', py)
        self.assertIn('CTF content verification failed for', py)

    def test_admin_view_has_reset_run_action(self):
        xml = (ROOT / "default" / "data" / "ui" / "views" / "admin.xml").read_text()
        js = (ROOT / "appserver" / "static" / "registration_admin.js").read_text()
        py = (ROOT / "bin" / "registration_rest.py").read_text()
        self.assertIn('id="ctfr-reset-run"', xml)
        self.assertIn('/admin/reset-run', js)
        self.assertIn('path == "admin/reset-run"', py)
        self.assertIn('delete_by_keyword', py)
        self.assertIn('ctf_hint_entitlements', py)
        self.assertIn('("scoreboard", "scoreboard_admin")', py)
        self.assertIn('| delete', py)
        self.assertIn('Generate Latest Scores and Ranks', py)


if __name__ == "__main__":
    unittest.main()
