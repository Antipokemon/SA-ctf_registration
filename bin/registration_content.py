from __future__ import annotations

import csv
import io
import re
from datetime import datetime


LEGACY_QUESTION_FIELDS = [
    "ctf_id",
    "Number",
    "Question",
    "StartTime",
    "EndTime",
    "BasePoints",
    "AdditionalBonusPoints",
    "AdditionalBonusInstructions",
]
LEGACY_ANSWER_FIELDS = ["ctf_id", "Number", "Answer"]
LEGACY_HINT_FIELDS = ["ctf_id", "Number", "HintNumber", "Hint", "HintCost"]

NATIVE_QUESTION_FIELDS = ["question_id", "question", "points"]
NATIVE_ANSWER_FIELDS = ["question_id", "answer"]
NATIVE_HINT_FIELDS = ["question_id", "hint_number", "hint", "hint_cost"]


def _clean_csv_text(text):
    return str(text or "").lstrip("\ufeff")


def _read_rows(text, label):
    if not str(text or "").strip():
        raise ValueError(f"{label} CSV is empty")

    reader = csv.DictReader(io.StringIO(_clean_csv_text(text)))
    headers = list(reader.fieldnames or [])
    rows = []
    for row_number, row in enumerate(reader, start=2):
        normalized = {
            str(key): str(value or "").strip()
            for key, value in row.items()
            if key is not None
        }
        if not any(normalized.values()):
            continue
        normalized["_csv_row"] = row_number
        rows.append(normalized)
    return headers, rows


def _require_columns(headers, required_fields, label):
    missing = [field for field in required_fields if field not in headers]
    if missing:
        raise ValueError(
            f"{label} CSV is missing required column(s): {', '.join(missing)}"
        )


def _format_kind(headers, legacy_required, native_required, label):
    header_set = set(headers)
    if set(legacy_required).issubset(header_set):
        return "legacy"
    if set(native_required).issubset(header_set):
        return "native"

    legacy_missing = [f for f in legacy_required if f not in header_set]
    native_missing = [f for f in native_required if f not in header_set]
    raise ValueError(
        f"{label} CSV does not match a supported format. "
        f"Legacy format is missing: {', '.join(legacy_missing)}. "
        f"Silk Specter format is missing: {', '.join(native_missing)}."
    )


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
            f"{label} CSV row {row_number} has ctf_id={found!r}; "
            f"expected {expected_ctf_id!r}"
        )


def _strip_kv_metadata(rows):
    cleaned = []
    for row in rows or []:
        cleaned.append({
            key: str(value) if value is not None else ""
            for key, value in row.items()
            if not key.startswith("_")
        })
    return cleaned


def _native_number(question_id, row_number):
    question_id = str(question_id or "").strip()
    match = re.search(r"(\d+)$", question_id)
    if not match:
        raise ValueError(
            f"question_id must end in a numeric identifier at CSV row {row_number}: "
            f"{question_id!r}"
        )
    return _positive_int(match.group(1), "question_id numeric suffix", row_number)


def _question_id_map(questions):
    mapping = {}
    for row in questions or []:
        challenge_id = str(
            row.get("ChallengeID")
            or row.get("question_id")
            or ""
        ).strip()
        number_text = str(row.get("Number", "")).strip()
        if challenge_id and number_text:
            mapping[challenge_id] = int(number_text)
    return mapping


def _resolve_native_number(row, question_id_map, label):
    row_number = row["_csv_row"]
    question_id = str(row.get("question_id", "")).strip()
    if not question_id:
        raise ValueError(f"{label} CSV row {row_number} has an empty question_id")

    if question_id_map and question_id in question_id_map:
        return int(question_id_map[question_id])

    return _native_number(question_id, row_number)


def parse_questions_csv(
    ctf_id,
    csv_text,
    *,
    event_starts,
    event_ends,
    use_event_window=True,
):
    expected_ctf_id = str(ctf_id or "").strip().lower()
    headers, qrows = _read_rows(csv_text, "Questions")
    if not qrows:
        raise ValueError("Questions CSV contains no question rows")

    kind = _format_kind(
        headers,
        LEGACY_QUESTION_FIELDS,
        NATIVE_QUESTION_FIELDS,
        "Questions",
    )

    event_start_epoch = _iso_epoch(event_starts, "Event starts")
    event_end_epoch = _iso_epoch(event_ends, "Event ends")
    if event_end_epoch <= event_start_epoch:
        raise ValueError("Event ends must be later than event starts")

    questions = []
    question_numbers = set()
    challenge_ids = set()

    for row in qrows:
        row_number = row["_csv_row"]

        if kind == "legacy":
            _require_ctf_id(row, expected_ctf_id, "Questions")
            number = _positive_int(row.get("Number"), "Number", row_number)
            question = row.get("Question", "").strip()
            base_points = _positive_int(
                row.get("BasePoints"),
                "BasePoints",
                row_number,
                allow_zero=True,
            )
            bonus_points = _positive_int(
                row.get("AdditionalBonusPoints"),
                "AdditionalBonusPoints",
                row_number,
                allow_zero=True,
            )
            subject = (
                row.get("Subject", "").strip()
                or row.get("Category", "").strip()
            )
            challenge_id = (
                row.get("ChallengeID", "").strip()
                or f"Q{number:03d}"
            )
            bonus_instructions = row.get(
                "AdditionalBonusInstructions", ""
            ).strip()
            primary_sourcetype = row.get("PrimarySourcetype", "").strip()
            learning_objective = row.get("LearningObjective", "").strip()
            reference_spl = row.get("ReferenceSPL", "").strip()
        else:
            challenge_id = row.get("question_id", "").strip()
            if not challenge_id:
                raise ValueError(
                    f"question_id is required at CSV row {row_number}"
                )
            number = _native_number(challenge_id, row_number)
            question = row.get("question", "").strip()
            base_points = _positive_int(
                row.get("points"),
                "points",
                row_number,
                allow_zero=True,
            )
            bonus_points = 0
            subject = (
                row.get("Subject", "").strip()
                or row.get("subject", "").strip()
                or row.get("category", "").strip()
            )
            bonus_instructions = ""
            primary_sourcetype = row.get(
                "primary_sourcetype", ""
            ).strip()
            learning_objective = row.get(
                "learning_objective", ""
            ).strip()
            reference_spl = row.get("reference_spl", "").strip()

        if number in question_numbers:
            raise ValueError(f"Duplicate question Number {number}")
        question_numbers.add(number)

        if challenge_id in challenge_ids:
            raise ValueError(f"Duplicate question identifier {challenge_id!r}")
        challenge_ids.add(challenge_id)

        if not question:
            raise ValueError(f"Question is required at CSV row {row_number}")

        if use_event_window:
            start_time = event_start_epoch
            end_time = event_end_epoch
        else:
            if kind == "native":
                raise ValueError(
                    "Silk Specter question files do not contain StartTime/EndTime. "
                    "Enable 'Use event window for question times' when importing "
                    "Silk Specter content."
                )
            start_time = _epoch(row.get("StartTime"), "StartTime", row_number)
            end_time = _epoch(row.get("EndTime"), "EndTime", row_number)
            if end_time <= start_time:
                raise ValueError(
                    f"EndTime must be later than StartTime at CSV row {row_number}"
                )

        document = {
            "ctf_id": expected_ctf_id,
            "Number": str(number),
            "ChallengeID": challenge_id,
            "Question": question,
            "StartTime": str(start_time),
            "EndTime": str(end_time),
            "BasePoints": str(base_points),
            "AdditionalBonusPoints": str(bonus_points),
            "AdditionalBonusInstructions": bonus_instructions,
        }

        if subject:
            # Subject is canonical. Category remains for compatibility with older
            # scoreboard searches and existing content.
            document["Subject"] = subject
            document["Category"] = subject
        if primary_sourcetype:
            document["PrimarySourcetype"] = primary_sourcetype
        if learning_objective:
            document["LearningObjective"] = learning_objective
        if reference_spl:
            document["ReferenceSPL"] = reference_spl

        questions.append(document)

    return questions


def parse_answers_csv(ctf_id, csv_text, *, question_id_map=None):
    expected_ctf_id = str(ctf_id or "").strip().lower()
    headers, arows = _read_rows(csv_text, "Answers")
    if not arows:
        raise ValueError("Answers CSV contains no answer rows")

    kind = _format_kind(
        headers,
        LEGACY_ANSWER_FIELDS,
        NATIVE_ANSWER_FIELDS,
        "Answers",
    )

    answers = []
    answer_numbers = set()
    for row in arows:
        row_number = row["_csv_row"]

        if kind == "legacy":
            _require_ctf_id(row, expected_ctf_id, "Answers")
            number = _positive_int(row.get("Number"), "Number", row_number)
            answer = row.get("Answer", "").strip()
            answer_type = (
                row.get("AnswerType", "").strip()
                or row.get("answer_type", "").strip()
                or "case_insensitive"
            )
        else:
            number = _resolve_native_number(
                row,
                question_id_map or {},
                "Answers",
            )
            answer = row.get("answer", "").strip()
            answer_type = row.get("answer_type", "").strip() or "exact"

        if number in answer_numbers:
            raise ValueError(f"Duplicate answer Number {number}")
        if not answer:
            raise ValueError(f"Answer is required at CSV row {row_number}")
        answer_numbers.add(number)

        answers.append({
            "ctf_id": expected_ctf_id,
            "Number": str(number),
            "Answer": answer,
            "AnswerType": answer_type,
        })

    return answers


def parse_hints_csv(ctf_id, csv_text, *, question_id_map=None):
    expected_ctf_id = str(ctf_id or "").strip().lower()
    headers, hrows = _read_rows(csv_text, "Hints")

    # Blank hint files are allowed.
    if not hrows and not headers:
        return []

    kind = _format_kind(
        headers,
        LEGACY_HINT_FIELDS,
        NATIVE_HINT_FIELDS,
        "Hints",
    )

    hints = []
    hint_keys = set()
    for row in hrows:
        row_number = row["_csv_row"]

        if kind == "legacy":
            _require_ctf_id(row, expected_ctf_id, "Hints")
            number = _positive_int(row.get("Number"), "Number", row_number)
            hint_number = _positive_int(
                row.get("HintNumber"),
                "HintNumber",
                row_number,
            )
            hint = row.get("Hint", "").strip()
            hint_cost = _positive_int(
                row.get("HintCost"),
                "HintCost",
                row_number,
                allow_zero=True,
            )
        else:
            number = _resolve_native_number(
                row,
                question_id_map or {},
                "Hints",
            )
            hint_number = _positive_int(
                row.get("hint_number"),
                "hint_number",
                row_number,
            )
            hint = row.get("hint", "").strip()
            hint_cost = _positive_int(
                row.get("hint_cost"),
                "hint_cost",
                row_number,
                allow_zero=True,
            )

        key = (number, hint_number)
        if key in hint_keys:
            raise ValueError(
                f"Duplicate hint Number/HintNumber {number}/{hint_number}"
            )
        if not hint:
            raise ValueError(f"Hint is required at CSV row {row_number}")
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
    question_numbers = {
        int(str(row.get("Number", "0")))
        for row in questions
    }
    answer_numbers = {
        int(str(row.get("Number", "0")))
        for row in answers
    }

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
    qid_map = _question_id_map(questions)

    answers = parse_answers_csv(
        expected_ctf_id,
        answers_csv,
        question_id_map=qid_map,
    )
    hints = parse_hints_csv(
        expected_ctf_id,
        hints_csv,
        question_id_map=qid_map,
    )
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

    Both the legacy scoreboard CSV schema and the native Silk Specter repository
    schema are accepted. Any non-empty CSV replaces only that content type.
    Content types without a supplied CSV are retained from existing_content.
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

    # Questions must be resolved first so native answer/hint question_id values
    # can map to the scoreboard's numeric Number key.
    if supplied["questions"]:
        updates["questions"] = parse_questions_csv(
            expected_ctf_id,
            questions_csv,
            event_starts=event_starts,
            event_ends=event_ends,
            use_event_window=use_event_window,
        )
        effective["questions"] = updates["questions"]

    if not effective["questions"]:
        raise ValueError("CTF content has no questions; upload a Questions CSV")

    qid_map = _question_id_map(effective["questions"])

    if supplied["answers"]:
        updates["answers"] = parse_answers_csv(
            expected_ctf_id,
            answers_csv,
            question_id_map=qid_map,
        )
        effective["answers"] = updates["answers"]

    if supplied["hints"]:
        updates["hints"] = parse_hints_csv(
            expected_ctf_id,
            hints_csv,
            question_id_map=qid_map,
        )
        effective["hints"] = updates["hints"]

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
