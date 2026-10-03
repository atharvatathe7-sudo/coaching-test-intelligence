import { useEffect, useState } from "react";

import OmrBatchSummary, { IssueList } from "./OmrResult";
import OmrReview from "./OmrReview";
import ValidationReport from "./ValidationReport";
import { ApiError, apiFetch } from "./api";
import { postImport } from "./importClient";
import "./ImportPage.css";

function FileInput({ label, onChange }) {
  return (
    <label className="import-field">
      <span>{label}</span>
      <input
        accept=".csv,text/csv"
        onChange={(event) => onChange(event.target.files[0] || null)}
        type="file"
      />
    </label>
  );
}

function Stage({ number, title, hint, children }) {
  return (
    <section className="panel import-stage">
      <h2 className="section-title">
        {number}. {title}
      </h2>
      <p className="import-hint">{hint}</p>
      {children}
    </section>
  );
}

function RosterStage({ batchId }) {
  const [file, setFile] = useState(null);
  const [report, setReport] = useState(null);
  const [busy, setBusy] = useState(false);

  function changeFile(next) {
    setFile(next);
    setReport(null);
  }

  async function run(dryRun) {
    setBusy(true);
    setReport(
      await postImport(
        "roster",
        { batch_id: batchId, dry_run: dryRun },
        file
      )
    );
    setBusy(false);
  }

  return (
    <Stage
      number={1}
      title="Roster"
      hint="Columns: roll_number, name. Existing students are kept as they are."
    >
      <FileInput label="roster.csv" onChange={changeFile} />

      <div className="import-actions">
        <button
          disabled={!file || !batchId || busy}
          onClick={() => run(true)}
          type="button"
        >
          Validate
        </button>

        <button
          className="primary"
          disabled={report?.status !== "valid" || busy}
          onClick={() => run(false)}
          type="button"
        >
          Import roster
        </button>
      </div>

      {report?.status === "imported" && (
        <p className="import-success">
          {report.summary.students_created} students added.
        </p>
      )}

      <ValidationReport report={report} />
    </Stage>
  );
}

const EMPTY_TEST = {
  test_name: "",
  subject: "",
  test_date: "",
  marks_correct: "4",
  marks_wrong: "-1",
  marks_blank: "0",
};

function TestSetupStage({ batchId, onImported }) {
  const [fields, setFields] = useState(EMPTY_TEST);
  const [file, setFile] = useState(null);
  const [report, setReport] = useState(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);

  function reset() {
    setReport(null);
    setConfirmed(false);
  }

  function changeField(name, value) {
    setFields((current) => ({ ...current, [name]: value }));
    reset();
  }

  async function run(dryRun) {
    setBusy(true);

    const result = await postImport(
      "test-setup",
      {
        ...fields,
        batch_id: batchId,
        dry_run: dryRun,
        confirm_new_chapters_topics: confirmed,
      },
      file
    );

    setReport(result);
    setBusy(false);

    if (result.status === "imported") {
      onImported(result.summary.test_id);
    }
  }

  const needsConfirmation =
    report?.status === "valid" && report.summary.requires_confirmation;

  return (
    <Stage
      number={2}
      title="Test setup"
      hint="Columns: question_number, correct_answer (A–D), chapter, topic."
    >
      <div className="import-grid">
        <label className="import-field">
          <span>Test name</span>
          <input
            onChange={(e) => changeField("test_name", e.target.value)}
            type="text"
            value={fields.test_name}
          />
        </label>

        <label className="import-field">
          <span>Subject</span>
          <input
            onChange={(e) => changeField("subject", e.target.value)}
            type="text"
            value={fields.subject}
          />
        </label>

        <label className="import-field">
          <span>Test date</span>
          <input
            onChange={(e) => changeField("test_date", e.target.value)}
            type="date"
            value={fields.test_date}
          />
        </label>

        <label className="import-field">
          <span>Marks: correct</span>
          <input
            onChange={(e) => changeField("marks_correct", e.target.value)}
            type="text"
            value={fields.marks_correct}
          />
        </label>

        <label className="import-field">
          <span>Marks: wrong</span>
          <input
            onChange={(e) => changeField("marks_wrong", e.target.value)}
            type="text"
            value={fields.marks_wrong}
          />
        </label>

        <label className="import-field">
          <span>Marks: blank</span>
          <input
            onChange={(e) => changeField("marks_blank", e.target.value)}
            type="text"
            value={fields.marks_blank}
          />
        </label>
      </div>

      <FileInput
        label="test_setup.csv"
        onChange={(next) => {
          setFile(next);
          reset();
        }}
      />

      {needsConfirmation && (
        <label className="import-confirm">
          <input
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
            type="checkbox"
          />
          {report.summary.new_chapters} new chapters and{" "}
          {report.summary.new_topics} new topics will be created. Check
          this box to confirm.
        </label>
      )}

      <div className="import-actions">
        <button
          disabled={!file || !batchId || busy}
          onClick={() => run(true)}
          type="button"
        >
          Validate
        </button>

        <button
          className="primary"
          disabled={
            report?.status !== "valid" ||
            busy ||
            (needsConfirmation && !confirmed)
          }
          onClick={() => run(false)}
          type="button"
        >
          Import test setup
        </button>
      </div>

      {report?.status === "imported" && (
        <p className="import-success">
          Test created with {report.summary.questions} questions. Continue
          with the student answers below.
        </p>
      )}

      <ValidationReport report={report} />
    </Stage>
  );
}

function AnswersStage({ tests, testId, onTestChange, onDone }) {
  const [file, setFile] = useState(null);
  const [replace, setReplace] = useState(false);
  const [report, setReport] = useState(null);
  const [busy, setBusy] = useState(false);

  function reset() {
    setReport(null);
  }

  async function run(dryRun) {
    setBusy(true);
    setReport(
      await postImport(
        "answers",
        { test_id: testId, replace, dry_run: dryRun },
        file
      )
    );
    setBusy(false);
  }

  return (
    <Stage
      number={3}
      title="Student answers"
      hint="Columns: roll_number, question_number, answer (A–D, or blank). Imported answers are evaluated automatically."
    >
      <label className="import-field">
        <span>Test</span>
        <select
          onChange={(e) => {
            onTestChange(Number(e.target.value));
            reset();
          }}
          value={testId || ""}
        >
          <option value="">Select a test…</option>
          {tests.map((test) => (
            <option key={test.id} value={test.id}>
              {test.name} ({test.test_date})
            </option>
          ))}
        </select>
      </label>

      <FileInput
        label="answers.csv"
        onChange={(next) => {
          setFile(next);
          reset();
        }}
      />

      <label className="import-confirm">
        <input
          checked={replace}
          onChange={(e) => {
            setReplace(e.target.checked);
            reset();
          }}
          type="checkbox"
        />
        Replace existing answers for this test (questions and teacher
        actions are kept)
      </label>

      <div className="import-actions">
        <button
          disabled={!file || !testId || busy}
          onClick={() => run(true)}
          type="button"
        >
          Validate
        </button>

        <button
          className="primary"
          disabled={report?.status !== "valid" || busy}
          onClick={() => run(false)}
          type="button"
        >
          Import and evaluate
        </button>
      </div>

      {report?.status === "imported" && (
        <div className="import-success">
          Test imported and evaluated successfully (
          {report.summary.students_evaluated} students).{" "}
          <button
            className="primary"
            onClick={() => onDone(testId)}
            type="button"
          >
            Open dashboard
          </button>
        </div>
      )}

      <ValidationReport report={report} />
    </Stage>
  );
}

function OmrStage({ tests, testId, onTestChange, onOpenBatch }) {
  const [files, setFiles] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [templateId, setTemplateId] = useState("");
  const [batches, setBatches] = useState([]);
  const [rejected, setRejected] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    apiFetch("/api/omr/templates")
      .then((data) => {
        setTemplates(data.templates);
        setTemplateId((current) => current || data.templates[0]?.id || "");
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!testId) return;
    apiFetch(`/api/tests/${testId}/omr/batches`)
      .then((data) => setBatches(data.batches))
      .catch(() => setBatches([]));
  }, [testId]);

  async function upload() {
    setBusy(true);
    setError("");
    setRejected(null);

    const form = new FormData();
    form.append("template_id", templateId);
    files.forEach((file) => form.append("files", file));

    try {
      const result = await apiFetch(`/api/tests/${testId}/omr/import`, {
        method: "POST",
        body: form,
      });

      if (result.batch) {
        onOpenBatch(result.batch.id);
      } else {
        setRejected(result);
      }
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not reach the server. Check that the backend is running and try again."
      );
    }

    setBusy(false);
  }

  return (
    <Stage
      number={4}
      title="OMR answer sheets (images)"
      hint="Upload PNG or JPEG images of filled-in sheets for the selected test. Clear answers are accepted automatically; multi-marked, unexpected or unreadable ones are kept for you to review. Nothing is saved as an answer until you commit the batch."
    >
      <label className="import-field">
        <span>Test</span>
        <select
          onChange={(e) => {
            onTestChange(Number(e.target.value));
            setRejected(null);
          }}
          value={testId || ""}
        >
          <option value="">Select a test…</option>
          {tests.map((test) => (
            <option key={test.id} value={test.id}>
              {test.name} ({test.test_date})
            </option>
          ))}
        </select>
      </label>

      <label className="import-field">
        <span>Sheet template</span>
        <select onChange={(e) => setTemplateId(e.target.value)} value={templateId}>
          {templates.map((t) => (
            <option key={t.id} value={t.id}>
              {t.id} (v{t.version}, {t.questions} questions)
            </option>
          ))}
        </select>
      </label>

      <label className="import-field">
        <span>Sheet images</span>
        <input
          accept=".png,.jpg,.jpeg,image/png,image/jpeg"
          multiple
          onChange={(event) => {
            setFiles(Array.from(event.target.files || []));
            setRejected(null);
            setError("");
          }}
          type="file"
        />
      </label>
      {files.length > 0 && <p className="import-hint">{files.length} image(s) selected.</p>}

      <div className="import-actions">
        <button
          className="primary"
          disabled={!files.length || !testId || busy}
          onClick={upload}
          type="button"
        >
          {busy ? "Reading sheets…" : "Read sheets and open review"}
        </button>
      </div>

      {error && <div className="error-card">{error}</div>}

      {rejected && (
        <div className="validation-report status-invalid">
          <div className="report-heading">Upload rejected: nothing was stored</div>
          <IssueList items={rejected.errors} kind="error" title="Errors" />
          <IssueList items={rejected.warnings} kind="warning" title="Warnings" />
        </div>
      )}

      {batches.length > 0 && (
        <div className="omr-batch-list">
          <h3>Batches for this test</h3>
          {batches.map((batch) => (
            <OmrBatchSummary batch={batch} key={batch.id} onOpen={onOpenBatch} />
          ))}
        </div>
      )}
    </Stage>
  );
}

export default function ImportPage({ onClose }) {
  const [batches, setBatches] = useState([]);
  const [tests, setTests] = useState([]);
  const [batchId, setBatchId] = useState("");
  const [testId, setTestId] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [reviewBatchId, setReviewBatchId] = useState(null);

  async function loadTests() {
    const data = await apiFetch("/api/tests");
    setTests(data.tests || []);
  }

  useEffect(() => {
    async function load() {
      try {
        const data = await apiFetch("/api/batches");

        setBatches(data.batches || []);

        if (data.batches?.length) {
          setBatchId(String(data.batches[0].id));
        }

        await loadTests();
      } catch {
        setLoadError(
          "Could not load batches. Make sure the backend server is running."
        );
      }
    }

    load();
  }, []);

  const batchTests = tests.filter(
    (test) => String(test.batch_id) === batchId
  );

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <div className="brand">Coaching Test Intelligence</div>
          <div className="brand-subtitle">Import test data</div>
        </div>

        <button onClick={() => onClose(null)} type="button">
          ← Back to dashboard
        </button>
      </header>

      <main className="dashboard import-page">
        {reviewBatchId ? (
          <OmrReview
            batchId={reviewBatchId}
            onBack={() => setReviewBatchId(null)}
            onDone={onClose}
          />
        ) : (
          <>
            {loadError && <div className="error-card">{loadError}</div>}

            <section className="panel import-stage">
              <label className="import-field">
                <span>Batch</span>
                <select
                  onChange={(e) => {
                    setBatchId(e.target.value);
                    setTestId(null);
                  }}
                  value={batchId}
                >
                  {batches.map((batch) => (
                    <option key={batch.id} value={batch.id}>
                      {batch.name}
                    </option>
                  ))}
                </select>
              </label>

              <p className="import-hint">
                Import in order: roster, test setup, then student answers.
                Each file is validated first; nothing is saved until you
                import.
              </p>
            </section>

            <RosterStage batchId={batchId} />

            <TestSetupStage
              batchId={batchId}
              onImported={async (newTestId) => {
                try {
                  await loadTests();
                  setTestId(newTestId);
                } catch {
                  setLoadError("Could not refresh the test list.");
                }
              }}
            />

            <AnswersStage
              onDone={onClose}
              onTestChange={setTestId}
              testId={testId}
              tests={batchTests}
            />

            <OmrStage
              onOpenBatch={setReviewBatchId}
              onTestChange={setTestId}
              testId={testId}
              tests={batchTests}
            />
          </>
        )}
      </main>
    </div>
  );
}
