import { useEffect, useRef, useState } from "react";
import ImportPage from "./ImportPage";
import "./App.css";

const API = "";

function StatCard({ label, value, subtext }) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {subtext && <div className="stat-subtext">{subtext}</div>}
    </div>
  );
}

function SectionTitle({ children }) {
  return <h2 className="section-title">{children}</h2>;
}

function QuestionInvestigation({ investigation, onBack }) {
  const question = investigation.question;
  const performance = investigation.performance;
  const students = investigation.students || [];

  return (
    <div className="dashboard">
      <button className="back-button" onClick={onBack}>
        ← Back to Test Overview
      </button>

      <section className="hero investigation-hero">
        <div>
          <div className="eyebrow">QUESTION INVESTIGATION</div>

          <h1>
            Question {question.question_number}
          </h1>

          <p>
            {investigation.test_name} · {question.subject}
          </p>
        </div>

        <div className="hero-badge">
          {question.difficulty}
        </div>
      </section>

      <section className="question-meta-grid">
        <div className="meta-card">
          <div className="meta-label">Chapter</div>
          <div className="meta-value">
            {question.chapter_name || "—"}
          </div>
        </div>

        <div className="meta-card">
          <div className="meta-label">Topic</div>
          <div className="meta-value">
            {question.topic_name || "—"}
          </div>
        </div>

        <div className="meta-card">
          <div className="meta-label">Difficulty</div>
          <div className="meta-value">
            {question.difficulty || "—"}
          </div>
        </div>

        <div className="meta-card">
          <div className="meta-label">Correct Answer</div>
          <div className="meta-value answer-value">
            {question.correct_answer}
          </div>
        </div>
      </section>

      <section className="stats-grid investigation-stats">
        <StatCard
          label="Correct"
          value={performance.correct_count}
          subtext={`${performance.correct_percentage}% of students`}
        />

        <StatCard
          label="Wrong"
          value={performance.wrong_count}
          subtext={`${performance.wrong_percentage}% of students`}
        />

        <StatCard
          label="Blank"
          value={performance.blank_count}
          subtext={`${performance.blank_percentage}% of students`}
        />

        <StatCard
          label="Students"
          value={performance.total_students}
          subtext="responses evaluated"
        />
      </section>

      <section className="panel">
        <SectionTitle>Student Responses</SectionTitle>

        <div className="response-table">
          <div className="response-row response-header">
            <div>Roll No.</div>
            <div>Student</div>
            <div>Answer</div>
            <div>Result</div>
          </div>

          {students.map((student) => (
            <div
              className="response-row"
              key={student.student_id}
            >
              <div className="response-roll">
                {student.roll_number}
              </div>

              <div>
                {student.student_name}
              </div>

              <div className="student-answer">
                {student.answer || "—"}
              </div>

              <div>
                <span
                  className={`response-result ${student.result
                    .toLowerCase()
                    .replace(" ", "-")}`}
                >
                  {student.result}
                </span>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        <SectionTitle>Teacher Interpretation</SectionTitle>

        <p className="footer-text">
          This investigation shows how the batch performed on this
          specific question. Use the response pattern together with
          the chapter and topic information to decide whether the
          issue requires concept revision, question review, or another
          intervention.
        </p>
      </section>
    </div>
  );
}

function signed(value, suffix = "") {
  if (value == null) return "—";
  const rounded = Math.round(value * 100) / 100;
  return `${rounded > 0 ? "+" : ""}${rounded}${suffix}`;
}

function changeClass(value) {
  if (value == null) return "change-flat";
  if (value > 0) return "change-up";
  if (value < 0) return "change-down";
  return "change-flat";
}

const STATUS_LABELS = {
  improved: "Improved",
  declined: "Declined",
  unchanged: "Unchanged",
  only_in_current: "Only in current test",
  only_in_previous: "Only in previous test",
};

function ProgressRows({ rows }) {
  return (
    <div className="progress-rows">
      {rows.map((row) => {
        const id = row.topic_id ?? row.chapter_id;
        const name = row.topic_name ?? row.chapter_name;
        const compared = row.change_pp != null;

        return (
          <div className="progress-row" key={id}>
            <div className="progress-name">
              {name}
              {row.topic_name && (
                <span className="progress-chapter">
                  {row.chapter_name}
                </span>
              )}
            </div>

            <div className="progress-values">
              {compared
                ? `${row.previous_percentage}% → ${row.current_percentage}%`
                : "—"}
            </div>

            <div
              className={`progress-change ${changeClass(
                row.change_pp
              )}`}
            >
              {compared
                ? `${signed(row.change_pp)} pp`
                : STATUS_LABELS[row.status]}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function MoverList({ title, rows }) {
  return (
    <div className="mover-card">
      <div className="mover-title">{title}</div>

      {rows.length === 0 ? (
        <div className="footer-text">None</div>
      ) : (
        rows.map((row) => (
          <div
            className="mover-item"
            key={row.topic_id ?? row.chapter_id}
          >
            <span>{row.topic_name ?? row.chapter_name}</span>
            <span className={changeClass(row.change_pp)}>
              {signed(row.change_pp)} pp
            </span>
          </div>
        ))
      )}
    </div>
  );
}

function ProgressSection({ previousTest, progress, loading, error }) {
  if (!previousTest) {
    return (
      <section className="panel">
        <SectionTitle>Progress vs Previous Test</SectionTitle>
        <p className="footer-text">
          No earlier test for the same batch and subject was found,
          so there is nothing to compare against yet.
        </p>
      </section>
    );
  }

  if (loading) {
    return (
      <section className="panel">
        <SectionTitle>Progress vs Previous Test</SectionTitle>
        <p className="footer-text">Loading progress…</p>
      </section>
    );
  }

  if (error || !progress) {
    return (
      <section className="panel">
        <SectionTitle>Progress vs Previous Test</SectionTitle>
        <p className="footer-text">
          {error || "Progress data is not available."}
        </p>
      </section>
    );
  }

  const b = progress.batch_comparison;
  const s = progress.student_summary;

  return (
    <section className="panel progress-section">
      <SectionTitle>Progress vs Previous Test</SectionTitle>

      <p className="footer-text">
        Comparing with {progress.previous_test.name} (
        {progress.previous_test.test_date}) ·{" "}
        {progress.common_student_count} students appeared in both
        tests.
      </p>

      {progress.comparability_notes.map((note) => (
        <div className="progress-note" key={note}>
          {note}
        </div>
      ))}

      <div className="stats-grid">
        <StatCard
          label="Average Marks"
          value={`${b.average_previous_marks} → ${b.average_current_marks}`}
          subtext={`${signed(b.average_marks_change)} marks (${signed(
            b.marks_percentage_change_pp
          )} pp of maximum)`}
        />
        <StatCard
          label="Average Accuracy"
          value={`${b.average_previous_accuracy}% → ${b.average_current_accuracy}%`}
          subtext={`${signed(
            b.average_accuracy_change
          )} pp on attempted questions`}
        />
        <StatCard
          label="Students"
          value={`${s.improved} ↑  ${s.declined} ↓  ${s.unchanged} =`}
          subtext="improved · declined · unchanged (marks)"
        />
      </div>

      <div className="mover-grid">
        <MoverList
          title="Biggest topic improvements"
          rows={progress.biggest_improvements.topics}
        />
        <MoverList
          title="Biggest topic declines"
          rows={progress.biggest_declines.topics}
        />
        <MoverList
          title="Biggest chapter improvements"
          rows={progress.biggest_improvements.chapters}
        />
        <MoverList
          title="Biggest chapter declines"
          rows={progress.biggest_declines.chapters}
        />
      </div>

      <div className="two-column">
        <div>
          <div className="mover-title">Chapter progress</div>
          <ProgressRows rows={progress.chapter_progress} />
        </div>

        <div>
          <div className="mover-title">Topic progress</div>
          <ProgressRows rows={progress.topic_progress} />
        </div>
      </div>

      <p className="footer-text">
        Percentages are the share of correct responses, so tests of
        different sizes are comparable. Changes under{" "}
        {progress.unchanged_threshold_pp} percentage points are
        shown as unchanged. Topics with few questions can move
        noticeably from a single answer. This shows what changed,
        not why.
      </p>
    </section>
  );
}

const ACTION_TYPES = [
  ["review", "Review"],
  ["reteach", "Reteach"],
  ["revise", "Revise"],
  ["monitor", "Monitor"],
  ["no_action", "No action"],
];

function actionLabel(value) {
  const match = ACTION_TYPES.find(([key]) => key === value);
  return match ? match[1] : value;
}

function ActionTracker({ item, testId, actions, onSaved }) {
  const [actionType, setActionType] = useState("review");
  const [status, setStatus] = useState("planned");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const evidence = item.evidence || {};

  async function save() {
    try {
      setSaving(true);
      setError("");

      const response = await fetch(`${API}/api/actions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          test_id: testId,
          question_number: evidence.question_number ?? null,
          chapter_id: evidence.chapter_id ?? null,
          topic_id: evidence.topic_id ?? null,
          finding_type: item.type,
          finding_title: item.title,
          finding_reason: item.reason,
          action_type: actionType,
          status,
          note: note.trim() || null,
        }),
      });

      if (!response.ok) throw new Error("Save failed.");

      onSaved(await response.json());
      setNote("");
    } catch {
      setError("Could not save the action.");
    } finally {
      setSaving(false);
    }
  }

  async function markCompleted(action) {
    try {
      setError("");

      const response = await fetch(
        `${API}/api/actions/${action.id}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status: "completed" }),
        }
      );

      if (!response.ok) throw new Error("Update failed.");

      onSaved(await response.json());
    } catch {
      setError("Could not update the action.");
    }
  }

  return (
    <div className="action-tracker">
      {actions.map((action) => (
        <div className="action-record" key={action.id}>
          <div className="action-record-head">
            <strong>{actionLabel(action.action_type)}</strong>
            <span className={`action-status ${action.status}`}>
              {action.status}
            </span>
            {action.status === "planned" && (
              <button
                className="action-link"
                onClick={() => markCompleted(action)}
                type="button"
              >
                Mark completed
              </button>
            )}
          </div>
          {action.note && (
            <div className="action-note">{action.note}</div>
          )}
          <div className="action-meta">
            Recorded{" "}
            {new Date(action.created_at + "Z").toLocaleDateString()}
          </div>
        </div>
      ))}

      <div className="action-form">
        <select
          aria-label="Action type"
          value={actionType}
          onChange={(e) => setActionType(e.target.value)}
        >
          {ACTION_TYPES.map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>

        <select
          aria-label="Action status"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          <option value="planned">Planned</option>
          <option value="completed">Completed</option>
        </select>

        <button
          className="action-save"
          disabled={saving}
          onClick={save}
          type="button"
        >
          {saving ? "Saving…" : "Save"}
        </button>

        <input
          aria-label="Action note"
          className="action-note-input"
          maxLength={500}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Optional note"
          type="text"
          value={note}
        />
      </div>

      {error && <div className="action-error">{error}</div>}
    </div>
  );
}

function App() {
  const [tests, setTests] = useState([]);
  const [selectedTest, setSelectedTest] = useState(null);
  const [batch, setBatch] = useState(null);
  const [chaptersTopics, setChaptersTopics] = useState(null);
  const [actionReport, setActionReport] = useState(null);

  const [teacherActions, setTeacherActions] = useState([]);
  const [progress, setProgress] = useState(null);
  const [progressLoading, setProgressLoading] = useState(false);
  const [progressError, setProgressError] = useState("");

  const [investigation, setInvestigation] = useState(null);
  const [investigationLoading, setInvestigationLoading] = useState(false);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [view, setView] = useState("dashboard");
  const [testsVersion, setTestsVersion] = useState(0);
  const preferredTestId = useRef(null);

  useEffect(() => {
    async function loadTests() {
      try {
        const response = await fetch(`${API}/api/tests`);

        if (!response.ok) {
          throw new Error("Could not load tests.");
        }

        const data = await response.json();

        setTests(data.tests || []);

        if (data.tests?.length) {
          setSelectedTest(
            data.tests.find(
              (test) => test.id === preferredTestId.current
            ) || data.tests[0]
          );
        }
      } catch {
        setError(
          "Could not connect to the FastAPI backend. Make sure the backend server is running."
        );
      } finally {
        setLoading(false);
      }
    }

    loadTests();
  }, [testsVersion]);

  useEffect(() => {
    if (!selectedTest) return;

    async function loadAnalytics() {
      try {
        setLoading(true);
        setError("");
        setInvestigation(null);

        const [
          batchResponse,
          chapterResponse,
          actionResponse,
        ] = await Promise.all([
          fetch(
            `${API}/api/tests/${selectedTest.id}/analytics/batch`
          ),
          fetch(
            `${API}/api/tests/${selectedTest.id}/analytics/chapters-topics`
          ),
          fetch(
            `${API}/api/tests/${selectedTest.id}/action-report`
          ),
        ]);

        if (
          !batchResponse.ok ||
          !chapterResponse.ok ||
          !actionResponse.ok
        ) {
          throw new Error("Analytics request failed.");
        }

        const [
          batchData,
          chapterData,
          actionData,
        ] = await Promise.all([
          batchResponse.json(),
          chapterResponse.json(),
          actionResponse.json(),
        ]);

        setBatch(batchData);
        setChaptersTopics(chapterData);
        setActionReport(actionData);

        try {
          const actionsResponse = await fetch(
            `${API}/api/tests/${selectedTest.id}/actions`
          );

          setTeacherActions(
            actionsResponse.ok
              ? (await actionsResponse.json()).actions
              : []
          );
        } catch {
          setTeacherActions([]);
        }
      } catch {
        setError("Could not load test analytics.");
      } finally {
        setLoading(false);
      }
    }

    loadAnalytics();
  }, [selectedTest]);

  // Latest earlier test for the same batch and subject.
  const previousTest = selectedTest
    ? tests
        .filter(
          (test) =>
            test.id !== selectedTest.id &&
            test.batch_id === selectedTest.batch_id &&
            test.subject === selectedTest.subject &&
            (test.test_date < selectedTest.test_date ||
              (test.test_date === selectedTest.test_date &&
                test.id < selectedTest.id))
        )
        .sort((a, b) =>
          a.test_date === b.test_date
            ? b.id - a.id
            : a.test_date < b.test_date
            ? 1
            : -1
        )[0] || null
    : null;

  const previousTestId = previousTest?.id;
  const selectedTestId = selectedTest?.id;

  useEffect(() => {
    setProgress(null);
    setProgressError("");

    if (!selectedTestId || !previousTestId) return;

    let cancelled = false;

    async function loadProgress() {
      try {
        setProgressLoading(true);

        const response = await fetch(
          `${API}/api/tests/${previousTestId}/compare/${selectedTestId}`
        );

        if (!response.ok) {
          throw new Error("Progress request failed.");
        }

        const data = await response.json();

        if (!cancelled) setProgress(data);
      } catch {
        if (!cancelled) {
          setProgressError("Could not load progress comparison.");
        }
      } finally {
        if (!cancelled) setProgressLoading(false);
      }
    }

    loadProgress();

    return () => {
      cancelled = true;
    };
  }, [selectedTestId, previousTestId]);

  async function openInvestigation(item) {
    const questionNumber =
      item?.evidence?.question_number;

    if (!questionNumber || !selectedTest) {
      return;
    }

    try {
      setInvestigationLoading(true);
      setError("");

      const response = await fetch(
        `${API}/api/tests/${selectedTest.id}/questions/${questionNumber}/investigation`
      );

      if (!response.ok) {
        throw new Error(
          "Could not load question investigation."
        );
      }

      const data = await response.json();

      setInvestigation(data);
    } catch {
      setError("Could not load question investigation.");
    } finally {
      setInvestigationLoading(false);
    }
  }

  function recordAction(saved) {
    setTeacherActions((current) =>
      current.some((a) => a.id === saved.id)
        ? current.map((a) => (a.id === saved.id ? saved : a))
        : [...current, saved]
    );
  }

  function closeInvestigation() {
    setInvestigation(null);
    setError("");
  }

  const overview = batch?.overview || {};

  const chapters =
    chaptersTopics?.chapters || [];

  const topics =
    chaptersTopics?.topics || [];

  const difficultQuestions =
    batch?.difficult_questions || [];

  const questionCount = (batch?.chapters || []).reduce(
    (total, chapter) => total + (chapter.questions || 0),
    0
  );

  if (view === "import") {
    return (
      <ImportPage
        onClose={(testId) => {
          preferredTestId.current = testId ?? null;
          setTestsVersion((version) => version + 1);
          setView("dashboard");
        }}
      />
    );
  }

  if (investigation) {
    return (
      <div className="app-shell">
        <header className="topbar">
          <div>
            <div className="brand">
              Coaching Test Intelligence
            </div>

            <div className="brand-subtitle">
              Teacher diagnostic dashboard
            </div>
          </div>

          <div className="test-selector">
            <label htmlFor="test-select">
              Test
            </label>

            <select
              id="test-select"
              value={selectedTest?.id || ""}
              onChange={(event) => {
                const test = tests.find(
                  (item) =>
                    item.id ===
                    Number(event.target.value)
                );

                setSelectedTest(test);
              }}
            >
              {tests.map((test) => (
                <option
                  key={test.id}
                  value={test.id}
                >
                  {test.name}
                </option>
              ))}
            </select>
          </div>
        </header>

        <QuestionInvestigation
          investigation={investigation}
          onBack={closeInvestigation}
        />
      </div>
    );
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <div className="brand">
            Coaching Test Intelligence
          </div>

          <div className="brand-subtitle">
            Teacher diagnostic dashboard
          </div>
        </div>

        <div className="topbar-actions">
          <div className="test-selector">
            <label htmlFor="test-select">
              Test
            </label>

            <select
              id="test-select"
              value={selectedTest?.id || ""}
              onChange={(event) => {
                const test = tests.find(
                  (item) =>
                    item.id ===
                    Number(event.target.value)
                );

                setSelectedTest(test);
              }}
            >
              {tests.map((test) => (
                <option
                  key={test.id}
                  value={test.id}
                >
                  {test.name}
                </option>
              ))}
            </select>
          </div>

          <button
            className="import-button"
            onClick={() => setView("import")}
            type="button"
          >
            Import data
          </button>
        </div>
      </header>

      <main className="dashboard">
        {loading && (
          <div className="loading-card">
            Loading test intelligence...
          </div>
        )}

        {investigationLoading && (
          <div className="loading-card">
            Loading question investigation...
          </div>
        )}

        {error && (
          <div className="error-card">
            {error}
          </div>
        )}

        {!loading && !error && selectedTest && (
          <>
            <section className="hero">
              <div>
                <div className="eyebrow">
                  TEST DIAGNOSTIC
                </div>

                <h1>{selectedTest.name}</h1>

                <p>
                  {selectedTest.subject} ·{" "}
                  {selectedTest.test_date}
                </p>
              </div>

              <div className="hero-badge">
                Teacher view
              </div>
            </section>

            <section className="stats-grid">
              <StatCard
                label="Students"
                value={
                  batch?.student_count ?? "—"
                }
                subtext="students evaluated"
              />

              <StatCard
                label="Average Marks"
                value={
                  overview.average_marks ?? "—"
                }
                subtext="batch average"
              />

              <StatCard
                label="Average Accuracy"
                value={
                  overview.average_accuracy != null
                    ? `${overview.average_accuracy}%`
                    : "—"
                }
                subtext="attempted questions"
              />

              <StatCard
                label="Questions"
                value={
                  batch?.chapters ? questionCount : "—"
                }
                subtext="in this test"
              />
            </section>

            <section className="attention-section">
              <div className="section-heading-row">
                <SectionTitle>
                  Teacher Attention
                </SectionTitle>

                <span className="priority-count">
                  {actionReport?.priority_count ??
                    0}{" "}
                  priorities
                </span>
              </div>

              <div className="attention-grid">
                {(actionReport?.priorities || [])
                  .slice(0, 6)
                  .map((item, index) => (
                    <div
                      className="attention-card"
                      key={`${item.title}-${index}`}
                    >
                      <div className="attention-top">
                        <span
                          className={`priority ${item.priority}`}
                        >
                          {item.priority}
                        </span>

                        <span className="attention-type">
                          {item.type.replaceAll(
                            "_",
                            " "
                          )}
                        </span>
                      </div>

                      <h3>{item.title}</h3>

                      <p>{item.reason}</p>

                      <div className="suggested-action">
                        <strong>
                          Suggested action:
                        </strong>{" "}
                        {item.suggested_action}
                      </div>

                      {item?.evidence
                        ?.question_number && (
                        <button
                          className="investigate-hint"
                          onClick={() =>
                            openInvestigation(item)
                          }
                          type="button"
                        >
                          Tap to investigate Question{" "}
                          {
                            item.evidence
                              .question_number
                          }{" "}
                          →
                        </button>
                      )}

                      <ActionTracker
                        actions={teacherActions.filter(
                          (a) =>
                            a.finding_type === item.type &&
                            a.finding_title === item.title
                        )}
                        item={item}
                        onSaved={recordAction}
                        testId={selectedTest.id}
                      />
                    </div>
                  ))}
              </div>
            </section>

            <section className="two-column">
              <div className="panel">
                <SectionTitle>
                  Chapter Performance
                </SectionTitle>

                <div className="performance-list">
                  {chapters.map((chapter) => (
                    <div
                      className="performance-row"
                      key={chapter.chapter_id}
                    >
                      <div className="performance-name">
                        {chapter.chapter_name}
                      </div>

                      <div className="bar-track">
                        <div
                          className="bar-fill"
                          style={{
                            width: `${Math.min(
                              chapter.correct_percentage ||
                                0,
                              100
                            )}%`,
                          }}
                        />
                      </div>

                      <div className="percentage">
                        {
                          chapter.correct_percentage
                        }
                        %
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="panel">
                <SectionTitle>
                  Difficult Questions
                </SectionTitle>

                <div className="question-list">
                  {difficultQuestions
                    .slice(0, 8)
                    .map((question) => (
                      <div
                        className="question-row"
                        key={
                          question.question_number
                        }
                      >
                        <div className="question-number">
                          Q
                          {
                            question.question_number
                          }
                        </div>

                        <div className="question-details">
                          <div>
                            {
                              question.correct_percentage
                            }
                            % correct
                          </div>

                          <div className="mini-bar-track">
                            <div
                              className="mini-bar-fill"
                              style={{
                                width: `${Math.min(
                                  question.correct_percentage ||
                                    0,
                                  100
                                )}%`,
                              }}
                            />
                          </div>
                        </div>
                      </div>
                    ))}
                </div>
              </div>
            </section>

            <section className="panel">
              <SectionTitle>
                Topic Performance
              </SectionTitle>

              <div className="topic-grid">
                {topics.map((topic) => (
                  <div
                    className="topic-card"
                    key={topic.topic_id}
                  >
                    <div className="topic-name">
                      {topic.topic_name}
                    </div>

                    <div className="topic-value">
                      {topic.correct_percentage}%
                    </div>

                    <div className="topic-meta">
                      {topic.questions}{" "}
                      questions
                    </div>
                  </div>
                ))}
              </div>
            </section>

            <ProgressSection
              previousTest={previousTest}
              progress={progress}
              loading={progressLoading}
              error={progressError}
            />

            <section className="panel footer-panel">
              <div>
                <SectionTitle>
                  Diagnostic principle
                </SectionTitle>

                <p className="footer-text">
                  This dashboard identifies
                  performance patterns from the
                  test data. Teachers decide whether
                  the underlying cause requires
                  reteaching, revision, question
                  review, or another intervention.
                </p>
              </div>
            </section>
          </>
        )}
      </main>
    </div>
  );
}

export default App;
