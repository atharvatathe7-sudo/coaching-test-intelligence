// Observed result for a teacher action in the next comparable test.
// Describes an observed change only; it never states or implies cause.

const CAVEATS = {
  action_recorded_after_next_test:
    "The action was recorded after that test's date.",
  action_still_planned: "The action is still planned.",
  marking_scheme_differs: "Marking scheme differs between the tests.",
  test_reevaluated_after_action:
    "This test's answer key or answers were corrected after the action was recorded; the finding shown at that time may differ.",
};

const SKIP_REASONS = {
  target_absent: "not covered",
  no_answers: "no answers imported",
};

function pct(value) {
  return value == null ? "—" : `${value}% correct`;
}

function responses(count) {
  return `${count} ${count === 1 ? "response" : "responses"}`;
}

function signedPp(value) {
  const rounded = Math.round(value * 100) / 100;
  return `${rounded > 0 ? "+" : ""}${rounded} percentage points`;
}

function targetLabel(target) {
  if (!target) return "";

  if (target.via_question_number) {
    return `Topic of Question ${target.via_question_number}: ${target.name}`;
  }

  return `${target.level === "chapter" ? "Chapter" : "Topic"}: ${target.name}`;
}

export default function ActionOutcome({ outcome }) {
  if (!outcome) return null;

  const { status, target, next_test: next } = outcome;
  const hasNext = Boolean(next);

  let message = "";

  if (status === "no_target") {
    message =
      "This action is not linked to a topic or chapter, so it cannot be compared.";
  } else if (status === "no_subsequent_test") {
    message = "No later test with answers yet for this batch and subject.";
  } else if (status === "topic_absent") {
    message = "The topic does not appear in a later test yet.";
  } else if (status === "chapter_absent") {
    message = "The chapter does not appear in a later test yet.";
  } else if (status === "insufficient_data") {
    message = `Fewer than ${outcome.min_responses} responses in one of the tests, so no change is reported.`;
  }

  const skipped = outcome.skipped_tests || [];

  return (
    <div className="action-outcome">
      {target && <div className="outcome-target">{targetLabel(target)}</div>}

      {hasNext && (
        <div className="outcome-rows">
          <div>
            <span className="outcome-label">
              {outcome.source_test.name}
            </span>{" "}
            {pct(outcome.previous_percentage)} ·{" "}
            {responses(outcome.previous_responses)}
          </div>

          <div>
            <span className="outcome-label">
              Observed next test: {next.name}
            </span>{" "}
            {pct(outcome.next_percentage)} ·{" "}
            {responses(outcome.next_responses)}
          </div>

          {status === "measured" && (
            <div className="outcome-change">
              Change: <strong>{signedPp(outcome.change_pp)}</strong>
            </div>
          )}
        </div>
      )}

      {message && <div className="outcome-message">{message}</div>}

      {skipped.length > 0 && (
        <div className="outcome-meta">
          Skipped:{" "}
          {skipped
            .map(
              (test) =>
                `${test.name} (${SKIP_REASONS[test.reason] || test.reason})`
            )
            .join(", ")}
        </div>
      )}

      {(outcome.caveats || []).map((code) => (
        <div className="outcome-meta" key={code}>
          {CAVEATS[code] || code}
        </div>
      ))}

      {hasNext && <div className="outcome-note">{outcome.note}</div>}
    </div>
  );
}
