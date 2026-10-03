// Plain labels for OMR batch states (kept out of component files).

const STATUS_LABELS = {
  PROCESSING: "Reading sheets…",
  REVIEW_REQUIRED: "Review required",
  READY_TO_COMMIT: "Ready to commit",
  COMMITTED: "Committed",
  DISCARDED: "Discarded",
  FAILED: "Failed",
};

export function statusLabel(status) {
  return STATUS_LABELS[status] || status;
}
