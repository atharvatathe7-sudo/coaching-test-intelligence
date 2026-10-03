// Summary of an OMR batch, shared by the upload result, the list of
// pending batches and the review screen. Display only.

import { statusLabel } from "./omrLabels";

export function BatchCounts({ batch }) {
  const ready = batch.accepted_sheets;
  const needReview = batch.review_required_count;
  const errors = batch.error_count;
  const recognition = batch.recognition || {};

  return (
    <div className="omr-batch-counts">
      <div className="omr-batch-line">
        <strong>{batch.total_sheets} sheets</strong>
        <span className="omr-ok">✓ {ready} ready</span>
        <span className={needReview ? "omr-warn" : ""}>
          ⚠ {needReview} need review
        </span>
        <span className={errors ? "omr-bad" : ""}>✕ {errors} unreadable</span>
      </div>

      <dl className="omr-counts">
        {[
          ["Clear answers", recognition.recognized],
          ["Blank", recognition.blank],
          ["Multi-marked", recognition.multi_mark],
          ["Invalid", recognition.invalid],
          ["Missing", recognition.review_required],
        ].map(([label, value]) => (
          <div className={value ? "has-value" : ""} key={label}>
            <dt>{label}</dt>
            <dd>{value ?? 0}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function IssueList({ title, items, kind }) {
  if (!items?.length) return null;

  return (
    <div className={`report-issues report-${kind}`}>
      <h4>{title}</h4>
      <ul>
        {items.slice(0, 30).map((item, index) => (
          <li key={index}>
            {item.sheet && <div className="report-where">{item.sheet}</div>}
            <div>{item.message}</div>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function OmrBatchSummary({ batch, onOpen }) {
  return (
    <div className={`omr-batch-card status-${batch.status}`}>
      <div className="omr-batch-head">
        <span className="omr-batch-status">{statusLabel(batch.status)}</span>
        <span className="omr-batch-meta">
          Batch {batch.id} · {batch.template.id}
        </span>
        {onOpen && (
          <button onClick={() => onOpen(batch.id)} type="button">
            {batch.status === "COMMITTED" ? "View" : "Open review"}
          </button>
        )}
      </div>
      <BatchCounts batch={batch} />
    </div>
  );
}
