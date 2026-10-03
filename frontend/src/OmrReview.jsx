import { useCallback, useEffect, useState } from "react";

import OmrCrop from "./OmrCrop";
import { BatchCounts } from "./OmrResult";
import { statusLabel } from "./omrLabels";
import { ApiError, apiFetch } from "./api";

// Teacher review of one OMR batch: settle every doubtful answer, then
// commit. Nothing is saved as an answer until the commit succeeds.

const DETECTED_LABELS = {
  multi_mark: "More than one bubble marked",
  invalid: "An unexpected value",
  review_required: "No value was read",
};

const REASON_TITLES = {
  MULTI_MARK: "Multi-marked answer",
  INVALID_ANSWER: "Unexpected answer value",
  MISSING_ANSWER_FIELD: "Answer not read",
};

function describeDetected(detected) {
  if (detected.recognition_status === "multi_mark") {
    return detected.letters.join(" + ");
  }
  return detected.raw_value ? `"${detected.raw_value}"` : "nothing";
}

function errorMessage(err) {
  return err instanceof ApiError
    ? err.message
    : "Could not reach the server. Check that the backend is running and try again.";
}

function AnswerItem({ item, busy, onChoose }) {
  const label = `question ${item.question_number}`;

  return (
    <li className={`omr-item ${item.resolved ? "is-resolved" : "is-open"}`}>
      <div className="omr-item-head">
        <strong>
          Student: roll {item.roll_number ?? "?"} · Question {item.question_number}
        </strong>
        <span className="omr-reason">{REASON_TITLES[item.reason] || item.reason}</span>
      </div>
      <div className="import-hint">{item.filename}</div>

      <div className="omr-compare">
        <div className="omr-detected">
          <span className="omr-compare-label">OMR detected</span>
          <span className="omr-detected-value">{describeDetected(item.detected)}</span>
          <span className="import-hint">
            {DETECTED_LABELS[item.detected.recognition_status]}
          </span>
        </div>

        <div className="omr-selected">
          <span className="omr-compare-label">Final answer</span>
          <span className="omr-selected-value">
            {item.final_answer === "BLANK"
              ? "Blank"
              : item.final_answer || "— not chosen yet —"}
          </span>
          {item.resolved && item.reviewed_by && (
            <span className="import-hint">chosen by {item.reviewed_by}</span>
          )}
        </div>
      </div>

      <OmrCrop
        crop={item.crop}
        fullSrc={item.images.original}
        label={label}
        src={item.images.checked || item.images.original}
      />

      <div className="omr-choices" role="group" aria-label={`Choose the final answer for ${label}`}>
        {item.choices.map((choice) => (
          <button
            className={item.final_answer === choice ? "selected" : ""}
            disabled={busy}
            key={choice}
            onClick={() => onChoose(item, choice)}
            type="button"
          >
            {choice === "BLANK" ? "Blank" : choice}
          </button>
        ))}
      </div>
    </li>
  );
}

function SheetItem({ item, busy, onAssign }) {
  const [roll, setRoll] = useState("");

  return (
    <li className="omr-item is-open">
      <div className="omr-item-head">
        <strong>Sheet {item.sheet_index}: {item.filename}</strong>
        <span className="omr-reason">{item.message}</span>
      </div>

      <div className="omr-compare">
        <div className="omr-detected">
          <span className="omr-compare-label">OMR detected roll</span>
          <span className="omr-detected-value">{item.detected.roll_raw || "nothing"}</span>
        </div>
      </div>

      <OmrCrop
        crop={null}
        fullSrc={item.images.original}
        label="the roll number"
        src={item.images.original}
      />

      {item.resolvable ? (
        <div className="omr-roll-form">
          <label className="import-field">
            <span>Correct roll number (must be in the roster)</span>
            <input onChange={(e) => setRoll(e.target.value)} value={roll} />
          </label>
          <button
            disabled={busy || !roll.trim()}
            onClick={() => onAssign(item, roll.trim())}
            type="button"
          >
            Assign roll number
          </button>
        </div>
      ) : (
        <p className="import-hint">
          This sheet cannot be fixed here. Discard the batch and scan it again.
        </p>
      )}
    </li>
  );
}

export default function OmrReview({ batchId, onBack, onDone }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [showResolved, setShowResolved] = useState(true);
  const [replace, setReplace] = useState(false);
  const [problems, setProblems] = useState([]);
  const [outcome, setOutcome] = useState(null);

  const load = useCallback(async () => {
    try {
      setData(await apiFetch(`/api/omr/batches/${batchId}/review`));
      setError("");
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [batchId]);

  useEffect(() => {
    let cancelled = false;

    async function first() {
      try {
        const loaded = await apiFetch(`/api/omr/batches/${batchId}/review`);
        if (!cancelled) setData(loaded);
      } catch (err) {
        if (!cancelled) setError(errorMessage(err));
      }
    }

    first();

    return () => {
      cancelled = true;
    };
  }, [batchId]);

  async function act(call) {
    setBusy(true);
    setNotice("");
    setProblems([]);

    try {
      await call();
    } catch (err) {
      setError("");
      setNotice(errorMessage(err));
      if (err instanceof ApiError && err.data?.detail?.problems) {
        setProblems(err.data.detail.problems);
      }
    }

    await load();
    setBusy(false);
  }

  const choose = (item, choice) =>
    act(() =>
      apiFetch(`/api/omr/review/${item.id}`, {
        method: "POST",
        json: { final_answer: choice, revision: item.revision },
      })
    );

  const assign = (item, roll) =>
    act(() =>
      apiFetch(`/api/omr/sheets/${item.sheet_id}/roll`, {
        method: "POST",
        json: { roll_number: roll, revision: item.revision },
      })
    );

  const commit = () =>
    act(async () => {
      setOutcome(
        await apiFetch(`/api/omr/batches/${batchId}/commit`, {
          method: "POST",
          json: { replace },
        })
      );
    });

  const discard = () => {
    if (!window.confirm("Discard this batch? The scanned sheets and any review work will be deleted. Existing answers are not affected.")) {
      return;
    }
    act(async () => {
      await apiFetch(`/api/omr/batches/${batchId}/discard`, { method: "POST" });
      onBack();
    });
  };

  if (error) {
    return (
      <section className="panel import-stage">
        <div className="error-card">{error}</div>
        <button onClick={onBack} type="button">Back</button>
      </section>
    );
  }

  if (!data) {
    return <div className="loading-card">Loading the review…</div>;
  }

  const { batch, items } = data;
  const open = items.filter((i) => !i.resolved);
  const done = items.filter((i) => i.resolved);
  const final = batch.status === "COMMITTED" || batch.status === "DISCARDED";

  return (
    <div className="omr-review">
      <section className="panel import-stage">
        <button className="link-button" onClick={onBack} type="button">← Back to import</button>
        <h2 className="section-title">OMR batch: {batch.test_name}</h2>
        <p className="import-hint">
          {batch.test_date} · {batch.total_sheets} sheets ·{" "}
          <strong>{statusLabel(batch.status)}</strong>
        </p>
        <BatchCounts batch={batch} />

        {outcome && batch.status === "COMMITTED" && (
          <div className="import-success">
            Batch committed and evaluated ({outcome.students_evaluated} students).
            {!outcome.images_removed && " The stored images could not all be removed; they are safe to delete later."}{" "}
            <button className="primary" onClick={() => onDone(batch.test_id)} type="button">
              Open dashboard
            </button>
          </div>
        )}
        {batch.status === "COMMITTED" && !outcome && (
          <div className="import-success">This batch was committed.</div>
        )}
        {batch.status === "FAILED" && (
          <div className="error-card">This batch could not be read. Discard it and upload the sheets again.</div>
        )}
        {notice && <div className="error-card" role="alert">{notice}</div>}
        {problems.length > 0 && (
          <ul className="omr-problems">
            {problems.slice(0, 20).map((p, i) => (
              <li key={i}>{p.sheet ? `${p.sheet}: ` : ""}{p.message}</li>
            ))}
          </ul>
        )}
      </section>

      {!final && batch.status !== "FAILED" && (
        <section className="panel import-stage">
          <h2 className="section-title">
            {open.length ? `${open.length} to review` : "Everything is settled"}
          </h2>
          <p className="import-hint">
            Choose the answer each student meant. What the OMR engine detected is shown
            beside your choice and is never overwritten.
          </p>

          <ul className="omr-items">
            {open.map((item) =>
              item.kind === "answer" ? (
                <AnswerItem busy={busy} item={item} key={`a${item.id}`} onChoose={choose} />
              ) : (
                <SheetItem busy={busy} item={item} key={`s${item.id}-${item.reason}`} onAssign={assign} />
              )
            )}
          </ul>

          {done.length > 0 && (
            <>
              <button className="link-button" onClick={() => setShowResolved(!showResolved)} type="button">
                {showResolved ? "Hide" : "Show"} {done.length} resolved
              </button>
              {showResolved && (
                <ul className="omr-items">
                  {done.map((item) => (
                    <AnswerItem busy={busy} item={item} key={`a${item.id}`} onChoose={choose} />
                  ))}
                </ul>
              )}
            </>
          )}
        </section>
      )}

      {!final && (
        <section className="panel import-stage">
          <h2 className="section-title">Commit</h2>
          <p className="import-hint">
            Committing saves every answer, evaluates the test and cannot be partly applied:
            if anything fails, nothing is saved and this batch stays here.
          </p>
          <label className="import-confirm">
            <input checked={replace} onChange={(e) => setReplace(e.target.checked)} type="checkbox" />
            Replace existing answers for this test
          </label>
          <div className="import-actions">
            <button
              className="primary"
              disabled={busy || batch.status !== "READY_TO_COMMIT"}
              onClick={commit}
              type="button"
            >
              Commit batch
            </button>
            <button disabled={busy} onClick={discard} type="button">Discard batch</button>
          </div>
          {batch.status !== "READY_TO_COMMIT" && batch.status !== "FAILED" && (
            <p className="import-hint">Settle every item above to enable the commit.</p>
          )}
        </section>
      )}
    </div>
  );
}
