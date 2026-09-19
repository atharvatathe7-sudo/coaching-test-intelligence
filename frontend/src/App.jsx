import { useEffect, useState } from "react";
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

function App() {
  const [tests, setTests] = useState([]);
  const [selectedTest, setSelectedTest] = useState(null);
  const [batch, setBatch] = useState(null);
  const [chaptersTopics, setChaptersTopics] = useState(null);
  const [actionReport, setActionReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

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
          setSelectedTest(data.tests[0]);
        }
      } catch (err) {
        setError(
          "Could not connect to the FastAPI backend. Make sure the backend server is running."
        );
      } finally {
        setLoading(false);
      }
    }

    loadTests();
  }, []);

  useEffect(() => {
    if (!selectedTest) return;

    async function loadAnalytics() {
      try {
        setLoading(true);
        setError("");

        const [batchResponse, chapterResponse, actionResponse] =
          await Promise.all([
            fetch(`${API}/api/tests/${selectedTest.id}/analytics/batch`),
            fetch(
              `${API}/api/tests/${selectedTest.id}/analytics/chapters-topics`
            ),
            fetch(`${API}/api/tests/${selectedTest.id}/action-report`),
          ]);

        if (
          !batchResponse.ok ||
          !chapterResponse.ok ||
          !actionResponse.ok
        ) {
          throw new Error("Analytics request failed.");
        }

        const [batchData, chapterData, actionData] = await Promise.all([
          batchResponse.json(),
          chapterResponse.json(),
          actionResponse.json(),
        ]);

        setBatch(batchData);
        setChaptersTopics(chapterData);
        setActionReport(actionData);
      } catch (err) {
        setError("Could not load test analytics.");
      } finally {
        setLoading(false);
      }
    }

    loadAnalytics();
  }, [selectedTest]);

  const overview = batch?.overview || {};

  const chapters = chaptersTopics?.chapters || [];
  const topics = chaptersTopics?.topics || [];

  const difficultQuestions = batch?.difficult_questions || [];

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <div className="brand">Coaching Test Intelligence</div>
          <div className="brand-subtitle">
            Teacher diagnostic dashboard
          </div>
        </div>

        <div className="test-selector">
          <label htmlFor="test-select">Test</label>
          <select
            id="test-select"
            value={selectedTest?.id || ""}
            onChange={(event) => {
              const test = tests.find(
                (item) => item.id === Number(event.target.value)
              );
              setSelectedTest(test);
            }}
          >
            {tests.map((test) => (
              <option key={test.id} value={test.id}>
                {test.name}
              </option>
            ))}
          </select>
        </div>
      </header>

      <main className="dashboard">
        {loading && (
          <div className="loading-card">
            Loading test intelligence...
          </div>
        )}

        {error && <div className="error-card">{error}</div>}

        {!loading && !error && selectedTest && (
          <>
            <section className="hero">
              <div>
                <div className="eyebrow">TEST DIAGNOSTIC</div>
                <h1>{selectedTest.name}</h1>
                <p>
                  {selectedTest.subject} · {selectedTest.test_date}
                </p>
              </div>

              <div className="hero-badge">
                Teacher view
              </div>
            </section>

            <section className="stats-grid">
              <StatCard
                label="Students"
                value={batch?.student_count ?? "—"}
                subtext="students evaluated"
              />

              <StatCard
                label="Average Marks"
                value={overview.average_marks ?? "—"}
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
                value={batch?.question_count ?? "—"}
                subtext="in this test"
              />
            </section>

            <section className="attention-section">
              <div className="section-heading-row">
                <SectionTitle>Teacher Attention</SectionTitle>
                <span className="priority-count">
                  {actionReport?.priority_count ?? 0} priorities
                </span>
              </div>

              <div className="attention-grid">
                {(actionReport?.priorities || [])
                  .slice(0, 6)
                  .map((item, index) => (
                    <div className="attention-card" key={`${item.title}-${index}`}>
                      <div className="attention-top">
                        <span className={`priority ${item.priority}`}>
                          {item.priority}
                        </span>
                        <span className="attention-type">
                          {item.type.replaceAll("_", " ")}
                        </span>
                      </div>

                      <h3>{item.title}</h3>

                      <p>{item.reason}</p>

                      <div className="suggested-action">
                        <strong>Suggested action:</strong>{" "}
                        {item.suggested_action}
                      </div>
                    </div>
                  ))}
              </div>
            </section>

            <section className="two-column">
              <div className="panel">
                <SectionTitle>Chapter Performance</SectionTitle>

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
                              chapter.correct_percentage || 0,
                              100
                            )}%`,
                          }}
                        />
                      </div>

                      <div className="percentage">
                        {chapter.correct_percentage}%
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="panel">
                <SectionTitle>Difficult Questions</SectionTitle>

                <div className="question-list">
                  {difficultQuestions.slice(0, 8).map((question) => (
                    <div
                      className="question-row"
                      key={question.question_number}
                    >
                      <div className="question-number">
                        Q{question.question_number}
                      </div>

                      <div className="question-details">
                        <div>
                          {question.correct_percentage}% correct
                        </div>

                        <div className="mini-bar-track">
                          <div
                            className="mini-bar-fill"
                            style={{
                              width: `${Math.min(
                                question.correct_percentage || 0,
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
              <SectionTitle>Topic Performance</SectionTitle>

              <div className="topic-grid">
                {topics.map((topic) => (
                  <div className="topic-card" key={topic.topic_id}>
                    <div className="topic-name">
                      {topic.topic_name}
                    </div>

                    <div className="topic-value">
                      {topic.correct_percentage}%
                    </div>

                    <div className="topic-meta">
                      {topic.question_count} questions
                    </div>
                  </div>
                ))}
              </div>
            </section>

            <section className="panel footer-panel">
              <div>
                <SectionTitle>Diagnostic principle</SectionTitle>
                <p className="footer-text">
                  This dashboard identifies performance patterns from the
                  test data. Teachers decide whether the underlying cause
                  requires reteaching, revision, question review, or another
                  intervention.
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
