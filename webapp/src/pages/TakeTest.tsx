import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { startTestAttempt, submitTestAttempt, flagAttempt } from '../api/client';
import { LockTask } from '../plugins/lockTask';

export default function TakeTest() {
  const { testId } = useParams();
  const [attempt, setAttempt] = useState<any>(null);
  const [flagCount, setFlagCount] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const studentId = localStorage.getItem('wandor_student_id') || 'demo-student';
    startTestAttempt(testId!, studentId).then(setAttempt);
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
    setSubmitting(true);
    try {
      if (attempt.type === 'mcq') {
        const payload = (Object.keys(answers) as string[]).map((question_id) => ({
          question_id,
          chosen_option: answers[question_id],
        }));
        const result = await submitTestAttempt(attempt.attempt_id, payload);
        alert(`Score: ${result.score}/${result.total}`);
      } else {
        await submitTestAttempt(attempt.attempt_id, []);
        alert('Test submitted successfully');
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (!attempt) {
    return (
      <div className="min-h-screen bg-cream flex items-center justify-center">
        <p className="text-sm text-ink/50">Loading test…</p>
      </div>
    );
  }

  /* ── MCQ variant ── */
  if (attempt.type === 'mcq') {
    return (
      <div className="min-h-screen bg-cream">
        <div className="max-w-xl mx-auto px-4 py-8">
          <h1 className="font-display text-2xl font-semibold text-ink tracking-tight mb-6">
            MCQ Test
          </h1>

          {attempt.questions?.map((q: any) => (
            <div
              key={q.id}
              className="bg-white rounded-xl border border-black/5 px-4 py-3.5 mb-4"
            >
              <p className="text-sm font-medium text-ink mb-3">{q.text}</p>
              <div className="space-y-2">
                {['a', 'b', 'c', 'd'].map((opt) => (
                  <label
                    key={opt}
                    className="flex items-center gap-2.5 text-sm text-ink/70 cursor-pointer hover:text-ink transition-colors"
                  >
                    <input
                      type="radio"
                      name={q.id}
                      value={opt}
                      checked={answers[q.id] === opt}
                      onChange={() =>
                        setAnswers((prev) => ({ ...prev, [q.id]: opt }))
                      }
                      className="accent-teal-700"
                    />
                    {q[`option_${opt}`]}
                  </label>
                ))}
              </div>
            </div>
          ))}

          <button
            onClick={submitAndFinish}
            disabled={submitting}
            className="w-full rounded-lg bg-teal-800 text-white text-sm font-medium py-2.5 hover:bg-teal-900 disabled:opacity-60 transition-colors"
          >
            {submitting ? 'Submitting…' : 'Submit'}
          </button>
        </div>
      </div>
    );
  }

  /* ── Locked/document variant ── */
  return (
    <div className="min-h-screen bg-ink flex flex-col">
      {/* Status bar */}
      <div className="bg-black/20 px-4 py-3 flex items-center justify-between">
        <span className="text-xs font-medium text-white/70">
          Locked test in progress
        </span>
        {flagCount > 0 && (
          <span className="text-xs font-medium text-amber-400">
            ⚠ {flagCount} leave attempt{flagCount !== 1 ? 's' : ''} logged
          </span>
        )}
      </div>

      {/* Document iframe */}
      <div className="flex-1">
        <iframe
          src={attempt.document_url}
          className="w-full h-full"
          title="Test document"
        />
      </div>

      {/* Submit bar */}
      <div className="bg-black/20 px-4 py-3">
        <button
          onClick={submitAndFinish}
          disabled={submitting}
          className="w-full rounded-lg bg-teal-700 text-white text-sm font-medium py-2.5 hover:bg-teal-600 disabled:opacity-60 transition-colors"
        >
          {submitting ? 'Submitting…' : 'Submit test'}
        </button>
      </div>
    </div>
  );
}

