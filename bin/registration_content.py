from __future__ import annotations

import csv
import io
from datetime import datetime


QUESTION_FIELDS = [
    "ctf_id",
    "Number",
    "Question",
    "StartTime",
    "EndTime",
    "BasePoints",
    "AdditionalBonusPoints",
    "AdditionalBonusInstructions",
]
ANSWER_FIELDS = ["ctf_id", "Number", "Answer"]
HINT_FIELDS = ["ctf_id", "Number", "HintNumber", "Hint", "HintCost"]


def _clean_csv_text(text):
    return str(text or "").lstrip("\ufeff")


def _read_rows(text, label, required_fields):
    if not str(text or "").strip():
        raise ValueError(f"{label} CSV is empty")

    reader = csv.DictReader(io.StringIO(_clean_csv_text(text)))
    headers = list(reader.fieldnames or [])
    missing = [field for field in required_fields if field not in headers]
    if missing:
        raise ValueError(f"{label} CSV is missing required column(s): {', '.join(missing)}")

    rows = []
    for row_number, row in enumerate(reader, start=2):
        normalized = {key: str(value or "").strip() for key, value in row.items() if key is not None}
        if not any(normalized.values()):
            continue
        normalized["_csv_row"] = row_number
        rows.append(normalized)
    return rows


def _positive_int(value, field, row_number, allow_zero=False):
    try:
        result = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer at CSV row {row_number}") from exc
    if allow_zero:
        if result < 0:
            raise ValueError(f"{field} must be zero or greater at CSV row {row_number}")
    elif result <= 0:
        raise ValueError(f"{field} must be greater than zero at CSV row {row_number}")
    return result


def _epoch(value, field, row_number):
    try:
        result = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a Unix epoch integer at CSV row {row_number}") from exc
    if result <= 0:
        raise ValueError(f"{field} must be greater than zero at CSV row {row_number}")
    return result


def _iso_epoch(value, field):
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field} must be a valid ISO-8601 timestamp") from exc
    if dt.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return int(dt.timestamp())


def _require_ctf_id(row, expected_ctf_id, label):
    row_number = row["_csv_row"]
    found = str(row.get("ctf_id", "")).strip().lower()
    if not found:
        raise ValueError(f"{label} CSV row {row_number} has an empty ctf_id")
    if found != expected_ctf_id:
        raise ValueError(
            f"{label} CSV row {row_number} has ctf_id={found!r}; expected {expected_ctf_id!r}"
        )


def parse_ctf_content(
    ctf_id,
    questions_csv,
    answers_csv,
    hints_csv,
    *,
    event_starts,
    event_ends,
    use_event_window=True,
):
    """Validate and normalize scoreboard content for one CTF.

    The accepted files are the current multi-CTF staged formats.  The returned
    rows are ready for the ctf_questions, ctf_answers, and ctf_hints KV stores.
    """

    expected_ctf_id = str(ctf_id or "").strip().lower()
    if not expected_ctf_id:
        raise ValueError("ctf_id is required for content import")

    qrows = _read_rows(questions_csv, "Questions", QUESTION_FIELDS)
    arows = _read_rows(answers_csv, "Answers", ANSWER_FIELDS)
    hrows = _read_rows(hints_csv, "Hints", HINT_FIELDS)

    if not qrows:
        raise ValueError("Questions CSV contains no question rows")
    if not arows:
        raise ValueError("Answers CSV contains no answer rows")

    event_start_epoch = _iso_epoch(event_starts, "Event starts")
    event_end_epoch = _iso_epoch(event_ends, "Event ends")
    if event_end_epoch <= event_start_epoch:
        raise ValueError("Event ends must be later than event starts")

    questions = []
    question_numbers = set()
    for row in qrows:
        _require_ctf_id(row, expected_ctf_id, "Questions")
        row_number = row["_csv_row"]
        number = _positive_int(row.get("Number"), "Number", row_number)
        if number in question_numbers:
            raise ValueError(f"Duplicate question Number {number}")
        question_numbers.add(number)

        question = row.get("Question", "").strip()
        if not question:
            raise ValueError(f"Question is required at CSV row {row_number}")

        base_points = _positive_int(row.get("BasePoints"), "BasePoints", row_number, allow_zero=True)
        bonus_points = _positive_int(
            row.get("AdditionalBonusPoints"),
            "AdditionalBonusPoints",
            row_number,
            allow_zero=True,
        )

        if use_event_window:
            start_time = event_start_epoch
            end_time = event_end_epoch
        else:
            start_time = _epoch(row.get("StartTime"), "StartTime", row_number)
            end_time = _epoch(row.get("EndTime"), "EndTime", row_number)
            if end_time <= start_time:
                raise ValueError(f"EndTime must be later than StartTime at CSV row {row_number}")

        questions.append({
            "ctf_id": expected_ctf_id,
            "Number": str(number),
            "Question": question,
            "StartTime": str(start_time),
            "EndTime": str(end_time),
            "BasePoints": str(base_points),
            "AdditionalBonusPoints": str(bonus_points),
            "AdditionalBonusInstructions": row.get("AdditionalBonusInstructions", "").strip(),
        })

    answers = []
    answer_numbers = set()
    for row in arows:
        _require_ctf_id(row, expected_ctf_id, "Answers")
        row_number = row["_csv_row"]
        number = _positive_int(row.get("Number"), "Number", row_number)
        if number in answer_numbers:
            raise ValueError(f"Duplicate answer Number {number}")
        if number not in question_numbers:
            raise ValueError(f"Answer Number {number} does not match a question")
        answer = row.get("Answer", "").strip()
        if not answer:
            raise ValueError(f"Answer is required at CSV row {row_number}")
        answer_numbers.add(number)
        answers.append({
            "ctf_id": expected_ctf_id,
            "Number": str(number),
            "Answer": answer,
        })

    missing_answers = sorted(question_numbers - answer_numbers)
    if missing_answers:
        preview = ", ".join(str(number) for number in missing_answers[:10])
        suffix = "..." if len(missing_answers) > 10 else ""
        raise ValueError(f"Question(s) missing answers: {preview}{suffix}")

    hints = []
    hint_keys = set()
    for row in hrows:
        _require_ctf_id(row, expected_ctf_id, "Hints")
        row_number = row["_csv_row"]
        number = _positive_int(row.get("Number"), "Number", row_number)
        hint_number = _positive_int(row.get("HintNumber"), "HintNumber", row_number)
        if number not in question_numbers:
            raise ValueError(f"Hint for Number {number} does not match a question")
        key = (number, hint_number)
        if key in hint_keys:
            raise ValueError(f"Duplicate hint Number/HintNumber {number}/{hint_number}")
        hint = row.get("Hint", "").strip()
        if not hint:
            raise ValueError(f"Hint is required at CSV row {row_number}")
        hint_cost = _positive_int(row.get("HintCost"), "HintCost", row_number, allow_zero=True)
        hint_keys.add(key)
        hints.append({
            "ctf_id": expected_ctf_id,
            "Number": str(number),
            "HintNumber": str(hint_number),
            "Hint": hint,
            "HintCost": str(hint_cost),
        })

    return {
        "questions": questions,
        "answers": answers,
        "hints": hints,
        "counts": {
            "questions": len(questions),
            "answers": len(answers),
            "hints": len(hints),
        },
    }
