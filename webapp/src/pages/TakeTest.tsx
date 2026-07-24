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

  useEffect(() => {
    // studentId would come from student-facing auth once that's built - see README TODOs
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

  if (!attempt) return <p>Loading test...</p>;

  if (attempt.type === 'document') {
    return (
      <div>
        <h1>{attempt.type === 'document' ? 'Locked test' : ''}</h1>
        {flagCount > 0 && <p>⚠ Leaving the screen has been logged ({flagCount}x)</p>}
        <iframe src={attempt.document_url} style={{ width: '100%', height: '80vh' }} title="Test document" />
        <button onClick={() => submitAndFinish()}>Submit</button>
      </div>
    );
  }

  async function submitAndFinish() {
    const payload = Object.entries(answers).map(([question_id, chosen_option]) => ({ question_id, chosen_option }));
    const result = await submitTestAttempt(attempt.attempt_id, payload);
    alert(`Score: ${result.score}/${result.total}`);
  }

  return (
    <div>
      <h1>{attempt.questions ? 'MCQ Test' : ''}</h1>
      {attempt.questions?.map((q: any) => (
        <div key={q.id}>
          <p>{q.text}</p>
          {['a', 'b', 'c', 'd'].map((opt) => (
            <label key={opt}>
              <input
                type="radio"
                name={q.id}
                onChange={() => setAnswers((prev) => ({ ...prev, [q.id]: opt }))}
              />
              {q[`option_${opt}`]}
            </label>
          ))}
        </div>
      ))}
      <button onClick={submitAndFinish}>Submit</button>
    </div>
  );
}
