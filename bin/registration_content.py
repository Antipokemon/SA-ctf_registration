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
OPTIONAL_QUESTION_FIELDS = ["Subject", "Category", "ChallengeID"]


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


def _strip_kv_metadata(rows):
    cleaned = []
    for row in rows or []:
        cleaned.append({key: str(value) if value is not None else "" for key, value in row.items() if not key.startswith("_")})
    return cleaned


def parse_questions_csv(
    ctf_id,
    csv_text,
    *,
    event_starts,
    event_ends,
    use_event_window=True,
):
    expected_ctf_id = str(ctf_id or "").strip().lower()
    qrows = _read_rows(csv_text, "Questions", QUESTION_FIELDS)
    if not qrows:
        raise ValueError("Questions CSV contains no question rows")

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

        subject = row.get("Subject", "").strip() or row.get("Category", "").strip()
        challenge_id = row.get("ChallengeID", "").strip()

        document = {
            "ctf_id": expected_ctf_id,
            "Number": str(number),
            "Question": question,
            "StartTime": str(start_time),
            "EndTime": str(end_time),
            "BasePoints": str(base_points),
            "AdditionalBonusPoints": str(bonus_points),
            "AdditionalBonusInstructions": row.get("AdditionalBonusInstructions", "").strip(),
        }
        if subject:
            # Subject is the canonical grouping field. Category is also written for
            # backward compatibility with older scoreboard searches.
            document["Subject"] = subject
            document["Category"] = subject
        if challenge_id:
            document["ChallengeID"] = challenge_id

        questions.append(document)
    return questions


def parse_answers_csv(ctf_id, csv_text):
    expected_ctf_id = str(ctf_id or "").strip().lower()
    arows = _read_rows(csv_text, "Answers", ANSWER_FIELDS)
    if not arows:
        raise ValueError("Answers CSV contains no answer rows")

    answers = []
    answer_numbers = set()
    for row in arows:
        _require_ctf_id(row, expected_ctf_id, "Answers")
        row_number = row["_csv_row"]
        number = _positive_int(row.get("Number"), "Number", row_number)
        if number in answer_numbers:
            raise ValueError(f"Duplicate answer Number {number}")
        answer = row.get("Answer", "").strip()
        if not answer:
            raise ValueError(f"Answer is required at CSV row {row_number}")
        answer_numbers.add(number)
        answers.append({
            "ctf_id": expected_ctf_id,
            "Number": str(number),
            "Answer": answer,
        })
    return answers


def parse_hints_csv(ctf_id, csv_text):
    expected_ctf_id = str(ctf_id or "").strip().lower()
    hrows = _read_rows(csv_text, "Hints", HINT_FIELDS)

    hints = []
    hint_keys = set()
    for row in hrows:
        _require_ctf_id(row, expected_ctf_id, "Hints")
        row_number = row["_csv_row"]
        number = _positive_int(row.get("Number"), "Number", row_number)
        hint_number = _positive_int(row.get("HintNumber"), "HintNumber", row_number)
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
    return hints


def validate_content_relationships(questions, answers, hints):
    question_numbers = {int(str(row.get("Number", "0"))) for row in questions}
    answer_numbers = {int(str(row.get("Number", "0"))) for row in answers}

    for number in sorted(answer_numbers - question_numbers):
        raise ValueError(f"Answer Number {number} does not match a question")

    missing_answers = sorted(question_numbers - answer_numbers)
    if missing_answers:
        preview = ", ".join(str(number) for number in missing_answers[:10])
        suffix = "..." if len(missing_answers) > 10 else ""
        raise ValueError(f"Question(s) missing answers: {preview}{suffix}")

    for row in hints:
        number = int(str(row.get("Number", "0")))
        if number not in question_numbers:
            raise ValueError(f"Hint for Number {number} does not match a question")


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
    """Validate and normalize a complete scoreboard content set for one CTF."""

    expected_ctf_id = str(ctf_id or "").strip().lower()
    if not expected_ctf_id:
        raise ValueError("ctf_id is required for content import")

    questions = parse_questions_csv(
        expected_ctf_id,
        questions_csv,
        event_starts=event_starts,
        event_ends=event_ends,
        use_event_window=use_event_window,
    )
    answers = parse_answers_csv(expected_ctf_id, answers_csv)
    hints = parse_hints_csv(expected_ctf_id, hints_csv)
    validate_content_relationships(questions, answers, hints)

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


def parse_ctf_content_update(
    ctf_id,
    *,
    questions_csv="",
    answers_csv="",
    hints_csv="",
    existing_content=None,
    event_starts,
    event_ends,
    use_event_window=True,
):
    """Validate an independent content update against the complete current CTF.

    Any non-empty CSV replaces only that content type.  Content types without a
    supplied CSV are retained from ``existing_content``.  Relationships are
    validated against the resulting effective set before anything is written.
    """

    expected_ctf_id = str(ctf_id or "").strip().lower()
    if not expected_ctf_id:
        raise ValueError("ctf_id is required for content import")

    existing = existing_content or {}
    supplied = {
        "questions": bool(str(questions_csv or "").strip()),
        "answers": bool(str(answers_csv or "").strip()),
        "hints": bool(str(hints_csv or "").strip()),
    }
    if not any(supplied.values()):
        raise ValueError("At least one content CSV must be supplied")

    effective = {
        "questions": _strip_kv_metadata(existing.get("questions", [])),
        "answers": _strip_kv_metadata(existing.get("answers", [])),
        "hints": _strip_kv_metadata(existing.get("hints", [])),
    }
    updates = {}

    if supplied["questions"]:
        updates["questions"] = parse_questions_csv(
            expected_ctf_id,
            questions_csv,
            event_starts=event_starts,
            event_ends=event_ends,
            use_event_window=use_event_window,
        )
        effective["questions"] = updates["questions"]

    if supplied["answers"]:
        updates["answers"] = parse_answers_csv(expected_ctf_id, answers_csv)
        effective["answers"] = updates["answers"]

    if supplied["hints"]:
        updates["hints"] = parse_hints_csv(expected_ctf_id, hints_csv)
        effective["hints"] = updates["hints"]

    if not effective["questions"]:
        raise ValueError("CTF content has no questions; upload a Questions CSV")
    if not effective["answers"]:
        raise ValueError("CTF content has no answers; upload an Answers CSV")

    validate_content_relationships(
        effective["questions"],
        effective["answers"],
        effective["hints"],
    )

    return {
        "updates": updates,
        "effective": effective,
        "updated": list(updates.keys()),
        "counts": {name: len(rows) for name, rows in effective.items()},
        "updated_counts": {name: len(rows) for name, rows in updates.items()},
    }
