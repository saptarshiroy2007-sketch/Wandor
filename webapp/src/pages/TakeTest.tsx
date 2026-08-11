import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { startTestAttempt, submitTestAttempt, flagAttempt } from '../api/client';
import { LockTask } from '../plugins/lockTask';

/**
 * Handles both test types. For 'document' type, this is the screen that triggers
 * the native lock (via LockTask plugin) and listens for leave-attempt events,
 * forwarding each one to the backend flag endpoint. For 'mcq' it's a normal form.
 */
export default function TakeTest() {
  const { testId } = useParams();
  const [attempt, setAttempt] = useState<any>(null);
  const [flagCount, setFlagCount] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [submitted, setSubmitted] = useState<{ score: number; total: number } | null>(null);

  useEffect(() => {
    startTestAttempt(testId!).then(setAttempt);
  }, [testId]);

  useEffect(() => {
    if (!attempt || attempt.type !== 'document') return;

    LockTask.startLock({ attemptId: attempt.attempt_id });

    const listenerPromise = LockTask.addListener('leaveAttempt', async ({ eventType }) => {
      setFlagCount((n) => n + 1);
      await flagAttempt(attempt.attempt_id, eventType);
    });

    return () => {
      LockTask.stopLock();
      listenerPromise.then((l) => l.remove());
    };
  }, [attempt]);

  async function submitAndFinish() {
    const payload = Object.entries(answers).map(([question_id, chosen_option]) => ({ question_id, chosen_option }));
    const result = await submitTestAttempt(attempt.attempt_id, payload);
    setSubmitted({ score: result.score, total: result.total });
  }

  if (!attempt) return <div className="page" style={{ paddingTop: '20vh', textAlign: 'center' }}><p>Loading test…</p></div>;

  if (submitted) {
    return (
      <div className="page" style={{ paddingTop: '20vh', textAlign: 'center' }}>
        <h1>Submitted</h1>
        <p style={{ fontSize: 20, color: 'var(--ink)' }}>Score: {submitted.score}/{submitted.total}</p>
      </div>
    );
  }

  if (attempt.type === 'document') {
    return (
      <div className="page" style={{ maxWidth: '100%', padding: 12 }}>
        <div className="row" style={{ marginBottom: 8 }}>
          <h1>Locked test</h1>
          {flagCount > 0 && <span className="badge badge-danger">⚠ logged {flagCount}x</span>}
        </div>
        <iframe src={attempt.document_url} style={{ width: '100%', height: '78vh', border: '1px solid var(--rule)', borderRadius: 3 }} title="Test document" />
        <button style={{ marginTop: 12 }} onClick={submitAndFinish}>Submit</button>
      </div>
    );
  }

  return (
    <div className="page">
      <h1>MCQ test</h1>
      <div className="stack">
        {attempt.questions?.map((q: any, i: number) => (
          <div className="card" key={q.id}>
            <p style={{ color: 'var(--ink)', fontWeight: 500 }}>{i + 1}. {q.text}</p>
            <div className="stack">
              {['a', 'b', 'c', 'd'].map((opt) => (
                <label key={opt} className="omr-option" htmlFor={`${q.id}-${opt}`}>
                  <input
                    id={`${q.id}-${opt}`}
                    type="radio"
                    name={q.id}
                    checked={answers[q.id] === opt}
                    onChange={() => setAnswers((prev) => ({ ...prev, [q.id]: opt }))}
                  />
                  <span className="omr-bubble" />
                  {q[`option_${opt}`]}
                </label>
              ))}
            </div>
          </div>
        ))}
      </div>
      <button onClick={submitAndFinish}>Submit</button>
    </div>
  );
}
