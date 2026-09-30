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

    def test_javascript_submits_content_fields_independently(self):
        js = (ROOT / "appserver" / "static" / "registration_admin.js").read_text()
        self.assertIn("if (selectedFiles[0]) { payload.questions_csv = files[0]; }", js)
        self.assertIn("if (selectedFiles[1]) { payload.answers_csv = files[1]; }", js)
        self.assertIn("if (selectedFiles[2]) { payload.hints_csv = files[2]; }", js)
        self.assertNotIn("Select questions, answers, and hints CSV files together", js)
        self.assertIn("use_event_window", js)

    def test_backend_targets_all_content_at_admin_app(self):
        py = (ROOT / "bin" / "registration_rest.py").read_text()
        self.assertIn('SCOREBOARD_ADMIN_APP = "SA-ctf_scoreboard_admin"', py)
        self.assertIn('"questions": (SCOREBOARD_ADMIN_APP, "ctf_questions", ("Number",))', py)
        self.assertIn('"answers": (SCOREBOARD_ADMIN_APP, "ctf_answers", ("Number",))', py)
        self.assertIn('"hints": (SCOREBOARD_ADMIN_APP, "ctf_hints", ("Number", "HintNumber"))', py)

    def test_backend_verifies_content_after_write(self):
        py = (ROOT / "bin" / "registration_rest.py").read_text()
        self.assertIn("def _verify_ctf_content", py)
        self.assertIn("Content verification failed", py)
        self.assertIn("Verified CTF content", py)


if __name__ == "__main__":
    unittest.main()
