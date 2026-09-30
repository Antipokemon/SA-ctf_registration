import os
import sys
import unittest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "bin")))

from registration_content import parse_ctf_content, parse_ctf_content_update


CTF_ID = "asteron-easy-2026"
START = "2026-10-10T12:00:00Z"
END = "2026-10-12T12:00:00Z"


def questions(rows=None):
    rows = rows or [
        f'{CTF_ID},1,"What host?",1,2,100,0,""',
        f'{CTF_ID},2,"What IP?",3,4,80,0,""',
    ]
    return "ctf_id,Number,Question,StartTime,EndTime,BasePoints,AdditionalBonusPoints,AdditionalBonusInstructions\n" + "\n".join(rows) + "\n"


def answers(rows=None):
    rows = rows or [f"{CTF_ID},1,WEB-01", f"{CTF_ID},2,10.0.0.1"]
    return "ctf_id,Number,Answer\n" + "\n".join(rows) + "\n"


def hints(rows=None):
    rows = rows or [
        f'{CTF_ID},1,1,"Look at web logs",5',
        f'{CTF_ID},2,1,"Look at network logs",5',
    ]
    return "ctf_id,Number,HintNumber,Hint,HintCost\n" + "\n".join(rows) + "\n"


class RegistrationContentTests(unittest.TestCase):
    def parse(self, **kwargs):
        values = dict(
            ctf_id=CTF_ID,
            questions_csv=questions(),
            answers_csv=answers(),
            hints_csv=hints(),
            event_starts=START,
            event_ends=END,
            use_event_window=True,
        )
        values.update(kwargs)
        return parse_ctf_content(**values)

    def test_valid_content(self):
        content = self.parse()
        self.assertEqual(content["counts"], {"questions": 2, "answers": 2, "hints": 2})
        self.assertEqual(content["questions"][0]["Number"], "1")

    def test_event_window_overrides_question_times(self):
        content = self.parse()
        self.assertEqual(content["questions"][0]["StartTime"], "1791633600")
        self.assertEqual(content["questions"][0]["EndTime"], "1791806400")

    def test_explicit_question_times_can_be_preserved(self):
        q = questions([
            f'{CTF_ID},1,"What host?",1791633600,1791806400,100,0,""',
            f'{CTF_ID},2,"What IP?",1791633601,1791806399,80,0,""',
        ])
        content = self.parse(questions_csv=q, use_event_window=False)
        self.assertEqual(content["questions"][1]["StartTime"], "1791633601")

    def test_ctf_id_must_match(self):
        bad = questions([f'wrong-id,1,"What host?",1,2,100,0,""'])
        with self.assertRaisesRegex(ValueError, "expected 'asteron-easy-2026'"):
            self.parse(questions_csv=bad, answers_csv=answers([f"{CTF_ID},1,WEB-01"]), hints_csv="ctf_id,Number,HintNumber,Hint,HintCost\n")

    def test_duplicate_question_rejected(self):
        bad = questions([
            f'{CTF_ID},1,"One",1,2,100,0,""',
            f'{CTF_ID},1,"Two",1,2,100,0,""',
        ])
        with self.assertRaisesRegex(ValueError, "Duplicate question Number 1"):
            self.parse(questions_csv=bad)

    def test_missing_answer_rejected(self):
        with self.assertRaisesRegex(ValueError, "missing answers: 2"):
            self.parse(answers_csv=answers([f"{CTF_ID},1,WEB-01"]))

    def test_hint_for_unknown_question_rejected(self):
        bad = hints([f'{CTF_ID},99,1,"Nope",5'])
        with self.assertRaisesRegex(ValueError, "does not match a question"):
            self.parse(hints_csv=bad)

    def test_missing_header_rejected(self):
        bad = "ctf_id,Number,Question\nasteron-easy-2026,1,What host?\n"
        with self.assertRaisesRegex(ValueError, "missing required column"):
            self.parse(questions_csv=bad)

    def test_partial_question_update_uses_existing_answers_and_hints(self):
        existing = self.parse()
        updated_questions = questions([
            f'{CTF_ID},1,"Updated host question?",1,2,100,0,""',
            f'{CTF_ID},2,"Updated IP question?",3,4,80,0,""',
        ])
        content = parse_ctf_content_update(
            CTF_ID,
            questions_csv=updated_questions,
            existing_content=existing,
            event_starts=START,
            event_ends=END,
            use_event_window=True,
        )
        self.assertEqual(content["updated"], ["questions"])
        self.assertEqual(content["updated_counts"], {"questions": 2})
        self.assertEqual(content["counts"], {"questions": 2, "answers": 2, "hints": 2})
        self.assertEqual(content["effective"]["questions"][0]["Question"], "Updated host question?")
        self.assertEqual(content["effective"]["answers"][0]["Answer"], "WEB-01")

    def test_partial_question_update_rejects_orphaned_existing_answer(self):
        existing = self.parse()
        updated_questions = questions([f'{CTF_ID},1,"Only one?",1,2,100,0,""'])
        with self.assertRaisesRegex(ValueError, "Answer Number 2 does not match a question"):
            parse_ctf_content_update(
                CTF_ID,
                questions_csv=updated_questions,
                existing_content=existing,
                event_starts=START,
                event_ends=END,
                use_event_window=True,
            )

    def test_partial_hint_update_can_clear_hints(self):
        existing = self.parse()
        empty_hints = "ctf_id,Number,HintNumber,Hint,HintCost\n"
        content = parse_ctf_content_update(
            CTF_ID,
            hints_csv=empty_hints,
            existing_content=existing,
            event_starts=START,
            event_ends=END,
            use_event_window=True,
        )
        self.assertEqual(content["updated"], ["hints"])
        self.assertEqual(content["counts"]["hints"], 0)

    def test_partial_update_requires_existing_complete_content(self):
        with self.assertRaisesRegex(ValueError, "no answers"):
            parse_ctf_content_update(
                CTF_ID,
                questions_csv=questions(),
                existing_content={},
                event_starts=START,
                event_ends=END,
                use_event_window=True,
            )


if __name__ == "__main__":
    unittest.main()
