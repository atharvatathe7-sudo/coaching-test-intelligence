import { useState } from "react";

const MAX_SHOWN = 50;

const HEADINGS = {
  invalid: "Import rejected",
  valid: "Validation passed",
  imported: "Import complete",
};

function Issues({ title, items, kind }) {
  const [showAll, setShowAll] = useState(false);

  if (!items.length) return null;

  const shown = showAll ? items : items.slice(0, MAX_SHOWN);

  return (
    <div className={`report-issues report-${kind}`}>
      <h4>{title}</h4>

      <ul>
        {shown.map((item, index) => (
          <li key={index}>
            <div className="report-where">
              {item.file}
              {item.row ? ` — row ${item.row}` : ""}
              {item.field ? ` — ${item.field}` : ""}
              {item.value !== null && item.value !== undefined && item.value !== ""
                ? ` — ${String(item.value)}`
                : ""}
            </div>
            <div>{item.message}</div>
          </li>
        ))}
      </ul>

      {items.length > MAX_SHOWN && !showAll && (
        <button
          className="link-button"
          onClick={() => setShowAll(true)}
          type="button"
        >
          Show all {items.length}
        </button>
      )}
    </div>
  );
}

export default function ValidationReport({ report }) {
  if (!report) return null;

  const errors = report.errors || [];
  const warnings = report.warnings || [];

  return (
    <div className={`validation-report status-${report.status}`}>
      <div className="report-heading">
        {HEADINGS[report.status] || "Result"}
      </div>

      <div className="report-counts">
        {errors.length} {errors.length === 1 ? "error" : "errors"},{" "}
        {warnings.length}{" "}
        {warnings.length === 1 ? "warning" : "warnings"}
      </div>

      <Issues items={errors} kind="error" title="Errors" />
      <Issues items={warnings} kind="warning" title="Warnings" />
    </div>
  );
}
