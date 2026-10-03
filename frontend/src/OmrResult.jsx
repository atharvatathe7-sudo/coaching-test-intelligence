// Result of an OMR batch check/import. Display only: there is no review
// screen yet, so multi-marked and unreadable answers are listed, not fixed.

const HEADINGS = {
  accepted: "Sheets checked — ready to import",
  imported: "Import complete",
  review_required: "Review required",
  rejected: "Import rejected",
};

const COUNTS = [
  ["processed", "Sheets read"],
  ["accepted", "Sheets accepted"],
  ["recognized", "Answers read"],
  ["blank", "Blank"],
  ["multi_mark", "Multi-marked"],
  ["invalid", "Invalid"],
  ["review_required", "Missing"],
  ["unreadable", "Unreadable sheets"],
  ["duplicate", "Duplicate students"],
  ["unknown_student", "Unknown students"],
];

const MAX_SHOWN = 30;

function Issues({ title, items, kind }) {
  if (!items.length) return null;

  return (
    <div className={`report-issues report-${kind}`}>
      <h4>{title}</h4>
      <ul>
        {items.slice(0, MAX_SHOWN).map((item, index) => (
          <li key={index}>
            <div className="report-where">
              {[item.sheet, item.roll_number && `roll ${item.roll_number}`]
                .filter(Boolean)
                .join(" — ")}
            </div>
            <div>{item.message}</div>
          </li>
        ))}
      </ul>
      {items.length > MAX_SHOWN && (
        <p className="import-hint">…and {items.length - MAX_SHOWN} more.</p>
      )}
    </div>
  );
}

export default function OmrResult({ result }) {
  if (!result) return null;

  const errors = result.errors || [];
  const warnings = result.warnings || [];
  const review = result.review_items || [];

  return (
    <div className={`validation-report omr-result status-${result.status}`}>
      <div className="report-heading">
        {HEADINGS[result.status] || "Result"}
      </div>

      {result.message && <p className="omr-message">{result.message}</p>}

      <dl className="omr-counts">
        {COUNTS.map(([key, label]) => (
          <div className={result.counts?.[key] ? "has-value" : ""} key={key}>
            <dt>{label}</dt>
            <dd>{result.counts?.[key] ?? 0}</dd>
          </div>
        ))}
      </dl>

      <Issues items={errors} kind="error" title="Errors" />

      {review.length > 0 && (
        <div className="report-issues report-warning">
          <h4>
            Review required ({result.review_items_total}{" "}
            {result.review_items_total === 1 ? "answer" : "answers"})
          </h4>
          <ul>
            {review.slice(0, MAX_SHOWN).map((item, index) => (
              <li key={index}>
                <div className="report-where">
                  {item.sheet} — roll {item.roll_number ?? "?"} — Q
                  {item.question_number}
                </div>
                <div>
                  {item.status.replace("_", "-")}
                  {item.raw_value ? `: ${item.raw_value}` : ""}
                </div>
              </li>
            ))}
          </ul>
          {review.length > MAX_SHOWN && (
            <p className="import-hint">
              …and {result.review_items_total - MAX_SHOWN} more.
            </p>
          )}
        </div>
      )}

      <Issues items={warnings} kind="warning" title="Warnings" />
    </div>
  );
}
