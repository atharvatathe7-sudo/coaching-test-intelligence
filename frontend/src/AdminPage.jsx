import { useEffect, useState } from "react";

import ValidationReport from "./ValidationReport";
import { apiFetch } from "./api";
import { postImport } from "./importClient";
import "./ImportPage.css";

// Admin-only tools. The server enforces the admin role on every request;
// this page is only shown to admins as a convenience.

function UsersSection({ currentUser }) {
  const [users, setUsers] = useState([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [form, setForm] = useState({
    name: "",
    email: "",
    password: "",
    role: "teacher",
  });
  const [resetFor, setResetFor] = useState(null);
  const [resetPassword, setResetPassword] = useState("");

  // Bumped after every change to reload the list.
  const [version, setVersion] = useState(0);

  useEffect(() => {
    const controller = new AbortController();

    apiFetch("/api/users", { signal: controller.signal })
      .then((data) => setUsers(data.users))
      .catch((err) => {
        if (err.name !== "AbortError") setError(err.message);
      });

    return () => controller.abort();
  }, [version]);

  async function run(action, success) {
    setError("");
    setMessage("");

    try {
      await action();
      setMessage(success);
      setVersion((v) => v + 1);
    } catch (err) {
      setError(err.message);
    }
  }

  function createUser(event) {
    event.preventDefault();
    run(async () => {
      await apiFetch("/api/users", { method: "POST", json: form });
      setForm({ name: "", email: "", password: "", role: "teacher" });
    }, "User created.");
  }

  return (
    <section className="panel import-stage">
      <h2 className="section-title">Users</h2>
      <p className="import-hint">
        Teachers can see all batches in this institute. Disabling a user or
        resetting a password signs them out everywhere.
      </p>

      <table className="admin-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Email</th>
            <th>Role</th>
            <th>Status</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id}>
              <td>{u.name}</td>
              <td>{u.email}</td>
              <td>{u.role}</td>
              <td>
                {u.is_active ? "Active" : "Disabled"}
                {u.locked ? " (locked)" : ""}
              </td>
              <td className="admin-row-actions">
                {u.id !== currentUser.id && (
                  <>
                    <button
                      onClick={() =>
                        run(
                          () =>
                            apiFetch(`/api/users/${u.id}`, {
                              method: "PATCH",
                              json: { is_active: !u.is_active },
                            }),
                          u.is_active ? "User disabled." : "User enabled."
                        )
                      }
                      type="button"
                    >
                      {u.is_active ? "Disable" : "Enable"}
                    </button>
                    <button
                      onClick={() => {
                        setResetFor(u);
                        setResetPassword("");
                      }}
                      type="button"
                    >
                      Reset password
                    </button>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {resetFor && (
        <form
          className="import-actions"
          onSubmit={(event) => {
            event.preventDefault();
            run(async () => {
              await apiFetch(`/api/users/${resetFor.id}/password`, {
                method: "POST",
                json: { new_password: resetPassword },
              });
              setResetFor(null);
              setResetPassword("");
            }, `Password reset for ${resetFor.email}.`);
          }}
        >
          <input
            aria-label="New password"
            autoComplete="new-password"
            minLength={10}
            onChange={(e) => setResetPassword(e.target.value)}
            placeholder={`New password for ${resetFor.email}`}
            required
            type="password"
            value={resetPassword}
          />
          <button className="primary" type="submit">
            Set password
          </button>
          <button onClick={() => setResetFor(null)} type="button">
            Cancel
          </button>
        </form>
      )}

      <h3 className="admin-subtitle">Add a user</h3>
      <form className="import-grid" onSubmit={createUser}>
        <label className="import-field">
          <span>Name</span>
          <input
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            required
            type="text"
            value={form.name}
          />
        </label>
        <label className="import-field">
          <span>Email</span>
          <input
            onChange={(e) => setForm({ ...form, email: e.target.value })}
            required
            type="email"
            value={form.email}
          />
        </label>
        <label className="import-field">
          <span>Initial password (10+ characters)</span>
          <input
            autoComplete="new-password"
            minLength={10}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            required
            type="password"
            value={form.password}
          />
        </label>
        <label className="import-field">
          <span>Role</span>
          <select
            onChange={(e) => setForm({ ...form, role: e.target.value })}
            value={form.role}
          >
            <option value="teacher">Teacher</option>
            <option value="admin">Admin</option>
          </select>
        </label>
        <div className="import-actions">
          <button className="primary" type="submit">
            Create user
          </button>
        </div>
      </form>

      {message && <p className="import-success">{message}</p>}
      {error && <div className="error-card">{error}</div>}
    </section>
  );
}

function KeyCorrection({ test, onDone }) {
  const [file, setFile] = useState(null);
  const [report, setReport] = useState(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);

  async function run(dryRun) {
    setBusy(true);
    const result = await postImport(
      "answer-key",
      {
        test_id: test.id,
        dry_run: dryRun,
        confirm_new_chapters_topics: confirmed,
      },
      file
    );
    setReport(result);
    setBusy(false);
    if (result.status === "imported") onDone();
  }

  const summary = report?.summary || {};
  const needsConfirmation =
    report?.status === "valid" && summary.requires_confirmation;
  const changes = summary.key_changes || [];
  const mappings = summary.mapping_changes || [];

  return (
    <div className="admin-block">
      <h3 className="admin-subtitle">Correct the answer key</h3>
      <p className="import-hint">
        Upload the full corrected key (question_number, correct_answer,
        chapter, topic) listing every question. Validate first to see the
        exact changes. Applying re-evaluates the test; teacher actions are
        kept.
      </p>

      <input
        accept=".csv,text/csv"
        aria-label="Corrected answer key CSV"
        onChange={(e) => {
          setFile(e.target.files[0] || null);
          setReport(null);
          setConfirmed(false);
        }}
        type="file"
      />

      {(changes.length > 0 || mappings.length > 0) && (
        <div className="key-changes">
          <strong>
            {changes.length} answer key{changes.length === 1 ? "" : "s"}{" "}
            changed
            {mappings.length > 0 &&
              `, ${mappings.length} chapter/topic mapping(s) changed`}
          </strong>
          <ul>
            {changes.map((c) => (
              <li key={`k${c.question_number}`}>
                Q{c.question_number}: {c.from} → {c.to}
              </li>
            ))}
            {mappings.map((m) => (
              <li key={`m${m.question_number}`}>
                Q{m.question_number}: {m.chapter_from} / {m.topic_from} →{" "}
                {m.chapter_to} / {m.topic_to}
              </li>
            ))}
          </ul>
        </div>
      )}

      {needsConfirmation && (
        <label className="import-confirm">
          <input
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
            type="checkbox"
          />
          {summary.new_chapters} new chapters and {summary.new_topics} new
          topics will be created.
        </label>
      )}

      <div className="import-actions">
        <button disabled={!file || busy} onClick={() => run(true)} type="button">
          Validate
        </button>
        <button
          className="primary"
          disabled={
            report?.status !== "valid" ||
            busy ||
            !(changes.length || mappings.length) ||
            (needsConfirmation && !confirmed)
          }
          onClick={() => run(false)}
          type="button"
        >
          Apply correction
        </button>
      </div>

      {report?.status === "imported" && (
        <p className="import-success">
          Answer key corrected; {summary.students_reevaluated} students
          re-evaluated.
        </p>
      )}

      <ValidationReport report={report} />
    </div>
  );
}

function TestCorrections({ onChanged }) {
  const [tests, setTests] = useState([]);
  const [testId, setTestId] = useState("");
  const [fields, setFields] = useState(null);
  const [version, setVersion] = useState(0);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    apiFetch("/api/tests", { signal: controller.signal })
      .then((data) => setTests(data.tests))
      .catch((err) => {
        if (err.name !== "AbortError") setError(err.message);
      });
    return () => controller.abort();
  }, [version]);

  useEffect(() => {
    if (!testId) return;
    const controller = new AbortController();
    apiFetch(`/api/tests/${testId}`, { signal: controller.signal })
      .then((test) =>
        setFields({
          name: test.name,
          subject: test.subject,
          test_date: test.test_date,
          marks_correct: String(test.marks_correct),
          marks_wrong: String(test.marks_wrong),
          marks_blank: String(test.marks_blank),
        })
      )
      .catch((err) => {
        if (err.name !== "AbortError") setError(err.message);
      });
    return () => controller.abort();
  }, [testId, version]);

  const test = tests.find((t) => String(t.id) === testId);

  function refresh(text) {
    setMessage(text);
    setVersion((v) => v + 1);
    onChanged();
  }

  async function saveMetadata(event) {
    event.preventDefault();
    setError("");
    setMessage("");
    try {
      const result = await apiFetch(`/api/tests/${testId}`, {
        method: "PATCH",
        json: {
          ...fields,
          marks_correct: Number(fields.marks_correct),
          marks_wrong: Number(fields.marks_wrong),
          marks_blank: Number(fields.marks_blank),
        },
      });
      refresh(
        result.changed.length
          ? `Saved (${result.changed.join(", ")})${
              result.reevaluated ? "; test re-evaluated." : "."
            }`
          : "No changes."
      );
    } catch (err) {
      setError(err.message);
    }
  }

  async function deleteTest() {
    setError("");
    setMessage("");
    if (!window.confirm(`Delete "${test.name}" with all its answers and results?`)) {
      return;
    }
    try {
      await apiFetch(`/api/tests/${testId}`, { method: "DELETE" });
    } catch (err) {
      if (err.status !== 409) {
        setError(err.message);
        return;
      }
      if (!window.confirm(`${err.message}`)) return;
      try {
        await apiFetch(`/api/tests/${testId}?confirm_delete_actions=true`, {
          method: "DELETE",
        });
      } catch (second) {
        setError(second.message);
        return;
      }
    }
    setTestId("");
    setFields(null);
    refresh("Test deleted.");
  }

  return (
    <section className="panel import-stage">
      <h2 className="section-title">Test corrections</h2>

      <label className="import-field">
        <span>Test</span>
        <select
          onChange={(e) => {
            setTestId(e.target.value);
            setFields(null);
            setMessage("");
            setError("");
          }}
          value={testId}
        >
          <option value="">Select a test…</option>
          {tests.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name} ({t.test_date})
            </option>
          ))}
        </select>
      </label>

      {test && fields && (
        <>
          <form onSubmit={saveMetadata}>
            <h3 className="admin-subtitle">Test details</h3>
            <div className="import-grid">
              {[
                ["name", "Name", "text"],
                ["subject", "Subject", "text"],
                ["test_date", "Date", "date"],
                ["marks_correct", "Marks: correct", "text"],
                ["marks_wrong", "Marks: wrong", "text"],
                ["marks_blank", "Marks: blank", "text"],
              ].map(([key, label, type]) => (
                <label className="import-field" key={key}>
                  <span>{label}</span>
                  <input
                    onChange={(e) =>
                      setFields({ ...fields, [key]: e.target.value })
                    }
                    required
                    type={type}
                    value={fields[key]}
                  />
                </label>
              ))}
            </div>
            <p className="import-hint">
              Changing the marks re-evaluates the test. Changing the date or
              subject changes which tests count as "next" for action
              outcomes.
            </p>
            <div className="import-actions">
              <button className="primary" type="submit">
                Save details
              </button>
            </div>
          </form>

          <KeyCorrection key={test.id} onDone={() => refresh("")} test={test} />

          <div className="admin-block">
            <h3 className="admin-subtitle">Delete test</h3>
            <p className="import-hint">
              Removes the test with its questions, answers and results. If
              teacher actions exist you will be asked to confirm again.
            </p>
            <button className="danger" onClick={deleteTest} type="button">
              Delete this test
            </button>
          </div>
        </>
      )}

      {message && <p className="import-success">{message}</p>}
      {error && <div className="error-card">{error}</div>}
    </section>
  );
}

function StudentRow({ student, onSaved, onError }) {
  const [name, setName] = useState(student.name);
  const [roll, setRoll] = useState(student.roll_number);

  async function save() {
    try {
      await apiFetch(`/api/students/${student.id}`, {
        method: "PATCH",
        json: { name, roll_number: roll },
      });
      onSaved("Student updated.");
    } catch (err) {
      onError(err.message);
    }
  }

  async function remove() {
    if (!window.confirm(`Remove ${student.roll_number} from the roster?`)) return;
    try {
      await apiFetch(`/api/students/${student.id}`, { method: "DELETE" });
      onSaved("Student removed.");
    } catch (err) {
      onError(err.message);
    }
  }

  return (
    <tr>
      <td>
        <input
          aria-label="Roll number"
          onChange={(e) => setRoll(e.target.value)}
          value={roll}
        />
      </td>
      <td>
        <input
          aria-label="Name"
          onChange={(e) => setName(e.target.value)}
          value={name}
        />
      </td>
      <td className="admin-row-actions">
        <button
          disabled={name === student.name && roll === student.roll_number}
          onClick={save}
          type="button"
        >
          Save
        </button>
        <button onClick={remove} type="button">
          Remove
        </button>
      </td>
    </tr>
  );
}

function RosterCorrections() {
  const [batches, setBatches] = useState([]);
  const [batchId, setBatchId] = useState("");
  const [students, setStudents] = useState([]);
  const [version, setVersion] = useState(0);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    apiFetch("/api/batches", { signal: controller.signal })
      .then((data) => setBatches(data.batches))
      .catch((err) => {
        if (err.name !== "AbortError") setError(err.message);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!batchId) return;
    const controller = new AbortController();
    apiFetch(`/api/students?batch_id=${batchId}`, { signal: controller.signal })
      .then((data) => setStudents(data.students))
      .catch((err) => {
        if (err.name !== "AbortError") setError(err.message);
      });
    return () => controller.abort();
  }, [batchId, version]);

  return (
    <section className="panel import-stage">
      <h2 className="section-title">Roster corrections</h2>
      <p className="import-hint">
        Fix a student's name or roll number. Students with test answers
        cannot be removed.
      </p>

      <label className="import-field">
        <span>Batch</span>
        <select
          onChange={(e) => {
            setBatchId(e.target.value);
            setStudents([]);
          }}
          value={batchId}
        >
          <option value="">Select a batch…</option>
          {batches.map((b) => (
            <option key={b.id} value={b.id}>
              {b.name}
            </option>
          ))}
        </select>
      </label>

      {students.length > 0 && (
        <table className="admin-table">
          <thead>
            <tr>
              <th>Roll number</th>
              <th>Name</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {students.map((s) => (
              <StudentRow
                key={`${s.id}-${s.name}-${s.roll_number}`}
                onError={(text) => {
                  setMessage("");
                  setError(text);
                }}
                onSaved={(text) => {
                  setError("");
                  setMessage(text);
                  setVersion((v) => v + 1);
                }}
                student={s}
              />
            ))}
          </tbody>
        </table>
      )}

      {message && <p className="import-success">{message}</p>}
      {error && <div className="error-card">{error}</div>}
    </section>
  );
}

function AuditLog({ version }) {
  const [entries, setEntries] = useState([]);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    apiFetch("/api/audit?limit=50", { signal: controller.signal })
      .then((data) => setEntries(data.entries))
      .catch((err) => {
        if (err.name !== "AbortError") setError(err.message);
      });
    return () => controller.abort();
  }, [version]);

  return (
    <section className="panel import-stage">
      <h2 className="section-title">Recent changes</h2>
      {error && <div className="error-card">{error}</div>}
      <table className="admin-table">
        <thead>
          <tr>
            <th>When (UTC)</th>
            <th>Who</th>
            <th>Change</th>
            <th>Record</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((e) => (
            <tr key={e.id}>
              <td>{e.created_at.replace("T", " ").slice(0, 16)}</td>
              <td>{e.user.name}</td>
              <td>{e.action}</td>
              <td>
                {e.entity_type} {e.entity_id}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

export default function AdminPage({ user, onClose }) {
  const [auditVersion, setAuditVersion] = useState(0);
  const bumpAudit = () => setAuditVersion((v) => v + 1);

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <div className="brand">Coaching Test Intelligence</div>
          <div className="brand-subtitle">Administration</div>
        </div>

        <button onClick={() => onClose(null)} type="button">
          ← Back to dashboard
        </button>
      </header>

      <main className="dashboard import-page">
        <UsersSection currentUser={user} />
        <TestCorrections onChanged={bumpAudit} />
        <RosterCorrections />
        <AuditLog version={auditVersion} />
      </main>
    </div>
  );
}
