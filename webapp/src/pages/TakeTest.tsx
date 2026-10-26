import { useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { startTestAttempt, submitTestAttempt, flagAttempt, resolveApiUrl } from '../api/client';
import { LockTask } from '../plugins/lockTask';

/**
 * Handles both test types. For 'document' type, this is the screen that triggers
 * the native lock (via LockTask plugin) and listens for leave-attempt events,
 * forwarding each one to the backend flag endpoint. For 'mcq' it's a normal form.
 *
 * No Layout wrapper — spec: full-bleed, no nav, just the question/OMR/progress.
 */
export default function TakeTest() {
  const { testId } = useParams();
  const [attempt, setAttempt] = useState<any>(null);
  const [flagCount, setFlagCount] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [submitted, setSubmitted] = useState<{ score: number | null; total: number | null } | null>(null);
  const [loadError, setLoadError] = useState('');
  const [submitError, setSubmitError] = useState('');
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);
  const submittingRef = useRef(false);

  function errText(err: any, fallback: string) {
    const d = err?.response?.data?.detail;
    return typeof d === 'string' ? d : fallback;
  }

  useEffect(() => {
    startTestAttempt(testId!)
      .then((a) => { setAttempt(a); setSecondsLeft(typeof a.seconds_left === 'number' ? a.seconds_left : null); })
      .catch((err) => setLoadError(errText(err, 'Could not open this test.')));
  }, [testId]);

  // Countdown driven by the server's seconds_left; auto-submits at zero.
  useEffect(() => {
    if (secondsLeft === null || submitted) return;
    if (secondsLeft <= 0) { submitAndFinish(); return; }
    const id = setTimeout(() => setSecondsLeft((s) => (s === null ? s : s - 1)), 1000);
    return () => clearTimeout(id);
  }, [secondsLeft, submitted]);

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
    if (submittingRef.current || !attempt) return;
    submittingRef.current = true;
    setSubmitError('');
    const payload = Object.entries(answers).map(([question_id, chosen_option]) => ({ question_id, chosen_option }));
    try {
      const result = await submitTestAttempt(attempt.attempt_id, payload);
      setSubmitted({ score: result.score ?? null, total: result.total ?? null });
    } catch (err: any) {
      submittingRef.current = false;
      setSubmitError(errText(err, 'Could not submit. Check your connection and try again.'));
    }
  }

  const clock = secondsLeft === null ? null : `${Math.floor(secondsLeft / 60)}:${String(secondsLeft % 60).padStart(2, '0')}`;
  const timer = clock && <span className={`badge ${secondsLeft! < 60 ? 'badge-danger' : ''}`}>⏱ {clock}</span>;

  if (loadError) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '100vh', padding: 24, textAlign: 'center' }}>
        <h1>Can't open this test</h1>
        <p className="error">{loadError}</p>
        <a href="/home">Back to dashboard</a>
      </div>
    );
  }

  if (!attempt) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100vh', padding: 24 }}>
        <p>Loading test…</p>
      </div>
    );
  }

  if (submitted) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '100vh', padding: 24, textAlign: 'center' }}>
        <h1>Submitted</h1>
        <p style={{ fontSize: 20, color: 'var(--ink)', marginTop: 8 }}>
          {submitted.score === null ? 'Awaiting grading from your teacher.' : `Score: ${submitted.score}/${submitted.total}`}
        </p>
        <a href="/home">Back to dashboard</a>
      </div>
    );
  }

  if (attempt.type === 'document') {
    return (
      <div style={{ padding: 12 }}>
        <div className="row" style={{ marginBottom: 8 }}>
          <h1>Locked test</h1>
          <div className="hstack">{timer}{flagCount > 0 && <span className="badge badge-danger">⚠ logged {flagCount}x</span>}</div>
        </div>
        <iframe
          src={resolveApiUrl(attempt.document_url)}
          style={{ width: '100%', height: 'calc(100vh - 100px)', border: '1px solid var(--paper-line)' }}
          title="Test document"
        />
        {submitError && <p className="error">{submitError}</p>}
        <button style={{ marginTop: 12 }} onClick={submitAndFinish}>Submit</button>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 720, margin: '0 auto', padding: '24px 16px 48px' }}>
      <div className="row"><h1>MCQ test</h1>{timer}</div>
      <div className="stack">
        {attempt.questions?.map((q: any, i: number) => (
          <div className="card" key={q.id}>
            <p style={{ color: 'var(--ink)', fontWeight: 600, marginBottom: 8 }}>{i + 1}. {q.text}</p>
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
      {submitError && <p className="error">{submitError}</p>}
      <button onClick={submitAndFinish}>Submit</button>
    </div>
  );
}


