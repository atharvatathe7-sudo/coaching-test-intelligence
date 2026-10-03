"""
OMR normalization and validation (Stage 2B), without running the recogniser.

These exercise our own layer: how OMRChecker's output cells are turned
into recognition states, and how a batch of sheets is validated against a
test. Nothing here calculates marks.
"""

import pytest

from backend.app.omr import normalization, validation
from backend.app.omr.models import RecognitionStatus as S
from backend.app.omr.normalization import (
    METADATA_COLUMNS,
    normalize_answer,
    normalize_roll,
    normalize_sheet,
)
from backend.app.omr.service import answer_rows, answers_csv
from backend.app.omr.template import TemplateError, get_template, load_template
from backend.app.omr.validation import (
    check_template_covers_test,
    find_duplicate_answers,
    validate_sheets,
)

OPTIONS = ("A", "B", "C", "D")
TEMPLATE = get_template(None)


def sheet(index, roll, answers, name=None, **extra):
    """A normalised sheet from a fake OMRChecker row."""
    row = {
        "file_id": f"sheet_{index:04d}.png",
        "input_path": "/secret/server/path/in.png",
        "output_path": "/secret/server/path/out.png",
        "score": "999.0",
        "Roll": roll,
    }
    row.update({f"q{n}": v for n, v in answers.items()})
    row.update(extra)
    return normalize_sheet(index, name or f"s{index}", row, TEMPLATE, set(answers))


# ---------------------------------------------------------------- answers

@pytest.mark.parametrize("letter", ["A", "B", "C", "D"])
def test_single_option_is_recognized(letter):
    status, answer = normalize_answer(letter, OPTIONS)
    assert status is S.RECOGNIZED
    assert answer == letter


def test_lowercase_and_padding_are_normalised():
    assert normalize_answer(" b ", OPTIONS) == (S.RECOGNIZED, "B")


@pytest.mark.parametrize("raw", ["", "   "])
def test_empty_is_blank(raw):
    assert normalize_answer(raw, OPTIONS) == (S.BLANK, None)


@pytest.mark.parametrize("raw", ["AB", "AC", "BCD", "ABCD", "DA"])
def test_several_options_are_multi_mark_not_blank_and_not_a_guess(raw):
    status, answer = normalize_answer(raw, OPTIONS)
    assert status is S.MULTI_MARK
    assert status is not S.BLANK
    assert answer is None  # never reduced to one of the letters


@pytest.mark.parametrize("raw", ["E", "7", "a1", "-", "AA", "A,B", "=1+1"])
def test_unexpected_values_are_invalid_not_guessed(raw):
    status, answer = normalize_answer(raw, OPTIONS)
    assert status is S.INVALID
    assert answer is None


def test_missing_field_requires_review_and_is_not_blank():
    status, answer = normalize_answer(None, OPTIONS)
    assert status is S.REVIEW_REQUIRED
    assert status is not S.BLANK
    assert answer is None


def test_blank_and_multi_mark_stay_distinguishable_on_a_sheet():
    s = sheet(1, "123456", {1: "", 2: "AB"})
    states = {a.question_number: a.status for a in s.answers}
    assert states == {1: S.BLANK, 2: S.MULTI_MARK}
    assert s.answers[1].raw_value == "AB"  # the raw result is kept
    assert s.answers[1].needs_review and not s.answers[0].needs_review


# -------------------------------------------------------------------- roll

def test_valid_roll():
    assert normalize_roll("123456", TEMPLATE) == ("123456", None)


@pytest.mark.parametrize("raw", [None, "", "  "])
def test_missing_roll(raw):
    assert normalize_roll(raw, TEMPLATE) == (None, "roll_missing")


@pytest.mark.parametrize(
    "raw", ["12345", "1234567", "12a456", "12 456", "=1+1+1", "１２３４５６", "-12345"]
)
def test_malformed_roll(raw):
    assert normalize_roll(raw, TEMPLATE) == (None, "roll_malformed")


# ---------------------------------------------------------- metadata, score

def test_metadata_columns_are_known():
    assert METADATA_COLUMNS == {"file_id", "input_path", "output_path", "score"}


def test_omrchecker_score_and_paths_never_enter_the_model():
    s = sheet(1, "123456", {1: "A", 2: "B"})

    haystack = repr(s)
    assert "999" not in haystack            # the engine's score
    assert "secret" not in haystack         # file paths
    assert "input_path" not in haystack and "score" not in haystack

    rows = answer_rows([s])
    assert rows == [("123456", 1, "A"), ("123456", 2, "B")]
    assert b"999" not in answers_csv(rows) and b"secret" not in answers_csv(rows)


def test_metadata_never_becomes_an_answer_even_if_named_like_a_question():
    # A column that is metadata is dropped before any field is read.
    row = {"file_id": "q1", "input_path": "A", "output_path": "B", "score": "C",
           "Roll": "123456", "q1": ""}
    s = normalize_sheet(1, "s", row, TEMPLATE, {1})
    assert [a.status for a in s.answers] == [S.BLANK]


# ------------------------------------------------- question identification

def test_only_the_selected_tests_questions_become_answers():
    s = sheet(1, "123456", {1: "A", 2: "B"}, q3="C", q60="D")
    assert [a.question_number for a in s.answers] == [1, 2]
    assert "q3" in s.ignored_fields and "q60" in s.ignored_fields
    assert s.ignored_marked == 2  # the marks on those fields were not imported


def test_non_question_fields_are_ignored_but_reported():
    s = sheet(1, "123456", {1: "A"}, Section="X", extra_field="1")
    assert [a.question_number for a in s.answers] == [1]
    assert {"Section", "extra_field"} <= set(s.ignored_fields)

    result = validate_sheets([s], TEMPLATE, {"123456"})
    assert any(w.code == "unknown_fields_ignored" for w in result.warnings)


def test_roll_field_is_not_mistaken_for_a_question():
    s = sheet(1, "123456", {1: "A"})
    assert "Roll" not in s.ignored_fields
    assert all(a.question_number != 123456 for a in s.answers)


def test_template_must_cover_the_tests_questions():
    errors, _ = check_template_covers_test(TEMPLATE, {1, 2, 61})
    assert [e.code for e in errors] == ["template_incompatible"]

    errors, warnings = check_template_covers_test(TEMPLATE, {1, 2})
    assert errors == [] and [w.code for w in warnings] == ["template_fields_ignored"]

    errors, _ = check_template_covers_test(TEMPLATE, set())
    assert [e.code for e in errors] == ["test_has_no_questions"]


# ------------------------------------------------------------- validation

ROSTER = {"100001", "100002", "100003"}


def codes(result):
    return [e.code for e in result.errors]


def test_clean_batch_is_accepted():
    sheets = [sheet(1, "100001", {1: "A", 2: ""}), sheet(2, "100002", {1: "B", 2: "C"})]
    result = validate_sheets(sheets, TEMPLATE, ROSTER)
    assert result.status == "accepted" and not result.errors
    assert result.counts["accepted"] == 2 and result.counts["blank"] == 1
    assert result.counts["recognized"] == 3


def test_unknown_roll_is_an_error():
    result = validate_sheets([sheet(1, "999999", {1: "A"})], TEMPLATE, ROSTER)
    assert codes(result) == ["roll_unknown"]
    assert result.counts["unknown_student"] == 1 and result.status == "rejected"


def test_roll_match_is_exact_never_fuzzy():
    # one digit away from a real student must not be "corrected"
    result = validate_sheets([sheet(1, "100004", {1: "A"})], TEMPLATE, ROSTER)
    assert codes(result) == ["roll_unknown"]


def test_missing_and_malformed_rolls_are_errors():
    missing = validate_sheets([sheet(1, "", {1: "A"})], TEMPLATE, ROSTER)
    malformed = validate_sheets([sheet(1, "10000", {1: "A"})], TEMPLATE, ROSTER)
    assert codes(missing) == ["roll_missing"]
    assert codes(malformed) == ["roll_malformed"]


def test_duplicate_roll_is_an_error_and_neither_sheet_is_accepted():
    sheets = [sheet(1, "100001", {1: "A"}, name="first.png"),
              sheet(2, "100001", {1: "B"}, name="second.png")]
    result = validate_sheets(sheets, TEMPLATE, ROSTER)

    assert codes(result) == ["roll_duplicate"]
    assert "first.png" in result.errors[0].message
    assert result.counts["duplicate"] == 1
    assert result.sheet_states == {1: "rejected", 2: "rejected"}
    assert result.counts["accepted"] == 0


def test_duplicate_roll_and_question_pairs_are_never_silently_accepted():
    rows = [("100001", 1, "A"), ("100001", 2, "B"), ("100001", 1, "C")]
    assert find_duplicate_answers(rows) == [("100001", 1)]

    twin = [sheet(1, "100001", {1: "A"}), sheet(2, "100001", {1: "B"})]
    with pytest.raises(ValueError):
        answer_rows(twin)


def test_unreadable_sheet_is_an_error():
    unreadable = normalize_sheet(1, "bad.png", None, TEMPLATE, {1})
    result = validate_sheets([unreadable], TEMPLATE, ROSTER)
    assert codes(result) == ["sheet_unreadable"] and result.counts["unreadable"] == 1


def test_multi_mark_makes_the_batch_review_required_not_an_error():
    result = validate_sheets([sheet(1, "100001", {1: "A", 2: "AB"})], TEMPLATE, ROSTER)
    assert result.status == "review_required" and not result.errors
    assert result.counts["multi_mark"] == 1
    item = result.review_items[0]
    assert (item["question_number"], item["status"], item["raw_value"]) == (2, "multi_mark", "AB")


def test_invalid_and_missing_values_also_require_review():
    s = sheet(1, "100001", {1: "Z", 2: "A"})
    s2 = normalize_sheet(2, "x", {"Roll": "100002", "q1": "A"}, TEMPLATE, {1, 2})  # q2 absent
    result = validate_sheets([s, s2], TEMPLATE, ROSTER)
    assert result.status == "review_required"
    assert result.counts["invalid"] == 1 and result.counts["review_required"] == 1


def test_errors_take_priority_over_review():
    sheets = [sheet(1, "100001", {1: "AB"}), sheet(2, "999999", {1: "A"})]
    assert validate_sheets(sheets, TEMPLATE, ROSTER).status == "rejected"


def test_unresolved_answers_can_never_be_turned_into_final_rows():
    with pytest.raises(ValueError):
        answer_rows([sheet(1, "100001", {1: "AB"})])      # multi-mark
    with pytest.raises(ValueError):
        answer_rows([sheet(1, "100001", {1: "Z"})])       # invalid


def test_blank_becomes_the_existing_blank_representation():
    rows = answer_rows([sheet(1, "100001", {1: "", 2: "C"})])
    assert rows == [("100001", 1, ""), ("100001", 2, "C")]
    assert answers_csv(rows).decode().splitlines() == [
        "roll_number,question_number,answer", "100001,1,", "100001,2,C"
    ]


def test_no_sheets_is_an_error():
    assert codes(validate_sheets([], TEMPLATE, ROSTER)) == ["no_files"]


# --------------------------------------------------------------- templates

def test_template_manifest_is_checked_against_the_layout(tmp_path):
    import json, shutil
    src = TEMPLATE.directory
    for name in ("manifest.json", "template.json"):
        shutil.copy(src / name, tmp_path / name)

    assert load_template(tmp_path).id == TEMPLATE.id

    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["questions"]["last"] = 70            # the layout has no q61..q70
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(TemplateError):
        load_template(tmp_path)


def test_unknown_template_is_rejected():
    with pytest.raises(TemplateError):
        get_template("no-such-template")


def test_questions_can_be_an_explicit_list(tmp_path):
    import json, shutil
    for name in ("manifest.json", "template.json"):
        shutil.copy(TEMPLATE.directory / name, tmp_path / name)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["questions"] = {"label": "q{n}", "numbers": [1, 2, 3, 10, 20]}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))

    template = load_template(tmp_path)
    assert template.question_numbers == (1, 2, 3, 10, 20)
    assert list(template.question_columns) == ["q1", "q2", "q3", "q10", "q20"]


def test_template_files_beyond_the_manifest_are_copied_for_the_engine(tmp_path):
    import shutil
    from backend.app.omr.checker import BatchWorkspace
    for name in ("manifest.json", "template.json"):
        shutil.copy(TEMPLATE.directory / name, tmp_path / name)
    (tmp_path / "marker.png").write_bytes(b"marker")

    with BatchWorkspace(load_template(tmp_path)) as workspace:
        copied = sorted(p.name for p in workspace.input_dir.iterdir())
        root = workspace.root

    assert copied == ["config.json", "marker.png", "template.json"]   # not manifest.json
    assert not root.exists()
