import { useEffect, useState } from 'react';
import { createMcqTest, createDocumentTest, uploadTestDocument, listTests, testAnalytics, QuestionIn } from '../api/client';
import Layout from '../components/Layout';

interface TestOut {
  id: string; title: string; test_type: string; duration_minutes: number; batch?: string | null;
}

const EMPTY_QUESTION = (): QuestionIn => ({
  text: '', option_a: '', option_b: '', option_c: '', option_d: '', correct_option: 'a',
});

const OPTS: ('a' | 'b' | 'c' | 'd')[] = ['a', 'b', 'c', 'd'];

export default function CreateTest() {
  const [mode, setMode] = useState<'mcq' | 'document'>('mcq');
  const [tests, setTests] = useState<TestOut[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [info, setInfo] = useState('');

  // MCQ fields
  const [title, setTitle] = useState('');
  const [duration, setDuration] = useState(30);
  const [batch, setBatch] = useState('');
  const [questions, setQuestions] = useState<QuestionIn[]>([EMPTY_QUESTION()]);

  // Document fields
  const [docTitle, setDocTitle] = useState('');
  const [docDuration, setDocDuration] = useState(30);
  const [docBatch, setDocBatch] = useState('');
  const [file, setFile] = useState<File | null>(null);

  // Analytics
  const [openAnalyticsFor, setOpenAnalyticsFor] = useState<string | null>(null);
  const [analyticsLoading, setAnalyticsLoading] = useState(false);
  const [analyticsError, setAnalyticsError] = useState('');
  const [analytics, setAnalytics] = useState<{
    attempt_count: number; average_score: number; average_score_pct: number; weak_question_count: number;
    questions: { question_id: string; text: string; attempts: number; correct_count: number; correct_pct: number; is_weak: boolean }[];
  } | null>(null);

  function refresh() { listTests().then(setTests); }
  useEffect(refresh, []);

  function updateQuestion(index: number, field: keyof QuestionIn, value: string) {
    setQuestions((qs) => qs.map((q, i) => (i === index ? { ...q, [field]: value } : q)));
  }

  function addQuestion() { setQuestions((qs) => [...qs, EMPTY_QUESTION()]); }

  function removeQuestion(index: number) {
    setQuestions((qs) => qs.filter((_, i) => i !== index));
  }

  async function handleMcqSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(''); setInfo('');
    if (questions.length === 0) { setError('Add at least one question'); return; }
    const invalid = questions.findIndex(
      (q) => !q.text.trim() || !q.option_a.trim() || !q.option_b.trim() || !q.option_c.trim() || !q.option_d.trim()
    );
    if (invalid !== -1) { setError(`Question ${invalid + 1}: all fields are required`); return; }
    setSaving(true);
    try {
      const res = await createMcqTest({ title, duration_minutes: duration, batch: batch.trim() || undefined, questions });
      setInfo(`Created — ${res.questions_created} question(s) saved.`);
      setTitle(''); setBatch(''); setQuestions([EMPTY_QUESTION()]);
      refresh();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Could not create test');
    } finally {
      setSaving(false);
    }
  }

  async function handleDocSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) { setError('Choose a file first'); return; }
    setError(''); setInfo(''); setSaving(true);
    try {
      const uploaded = await uploadTestDocument(file);
      await createDocumentTest({ title: docTitle, document_url: uploaded.url, duration_minutes: docDuration, batch: docBatch.trim() || undefined });
      setInfo('Created.');
      setDocTitle(''); setDocBatch(''); setFile(null);
      refresh();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Could not create test');
    } finally {
      setSaving(false);
    }
  }

  async function handleToggleAnalytics(testId: string) {
    if (openAnalyticsFor === testId) { setOpenAnalyticsFor(null); return; }
    setOpenAnalyticsFor(testId); setAnalytics(null); setAnalyticsError(''); setAnalyticsLoading(true);
    try {
      setAnalytics(await testAnalytics(testId));
    } catch (err: any) {
      setAnalyticsError(err?.response?.data?.detail || 'Could not load analytics');
    } finally {
      setAnalyticsLoading(false);
    }
  }

  return (
    <Layout>
      <h1>Tests</h1>

      <div className="hstack" style={{ marginBottom: 12 }}>
        <button className={mode === 'mcq' ? '' : 'btn-ghost'} onClick={() => setMode('mcq')}>MCQ</button>
        <button className={mode === 'document' ? '' : 'btn-ghost'} onClick={() => setMode('document')}>Upload document</button>
      </div>

      {mode === 'mcq' ? (
        <form onSubmit={handleMcqSubmit} className="card stack">
          <input required placeholder="Title" value={title} onChange={(e) => setTitle(e.target.value)} />
          <div className="hstack">
            <div style={{ flex: 1 }}>
              <label>Duration (min)</label>
              <input type="number" min={1} value={duration} onChange={(e) => setDuration(+e.target.value)} />
            </div>
            <div style={{ flex: 1 }}>
              <label>Batch (optional — leave blank for all students)</label>
              <input placeholder="e.g. Class 10A" value={batch} onChange={(e) => setBatch(e.target.value)} />
            </div>
          </div>

          <div style={{ borderTop: '1px solid var(--rule)', paddingTop: 12 }}>
            <div className="row" style={{ marginBottom: 8 }}>
              <strong>Questions ({questions.length})</strong>
              <button type="button" className="btn-ghost btn-sm" onClick={addQuestion}>+ Add question</button>
            </div>

            {questions.map((q, i) => (
              <div key={i} className="card stack" style={{ marginBottom: 8 }}>
                <div className="row">
                  <label style={{ fontWeight: 600 }}>Q{i + 1}</label>
                  {questions.length > 1 && (
                    <button type="button" className="btn-danger btn-sm" onClick={() => removeQuestion(i)}>Remove</button>
                  )}
                </div>
                <input
                  required
                  placeholder="Question text"
                  value={q.text}
                  onChange={(e) => updateQuestion(i, 'text', e.target.value)}
                />
                {OPTS.map((opt) => (
                  <div key={opt} className="hstack" style={{ alignItems: 'center', gap: 8 }}>
                    <label className="omr-option" title={`Mark option ${opt.toUpperCase()} as correct`}>
                      <input
                        type="radio"
                        name={`correct-${i}`}
                        value={opt}
                        checked={q.correct_option === opt}
                        onChange={() => updateQuestion(i, 'correct_option', opt)}
                      />
                      <span className="omr-bubble" />
                    </label>
                    <input
                      required
                      placeholder={`Option ${opt.toUpperCase()}`}
                      value={q[`option_${opt}` as keyof QuestionIn] as string}
                      onChange={(e) => updateQuestion(i, `option_${opt}` as keyof QuestionIn, e.target.value)}
                      style={{ flex: 1 }}
                    />
                  </div>
                ))}
                <p style={{ margin: 0, fontSize: 12, color: 'var(--muted)' }}>
                  Correct: <strong>{q.correct_option.toUpperCase()}</strong> — select the bubble next to the right option
                </p>
              </div>
            ))}
          </div>

          {error && <p className="error">{error}</p>}
          {info && <p style={{ color: 'var(--accent)', fontSize: 13 }}>{info}</p>}
          <button type="submit" disabled={saving}>{saving ? 'Saving…' : 'Create test'}</button>
        </form>
      ) : (
        <form onSubmit={handleDocSubmit} className="card stack">
          <input required placeholder="Title" value={docTitle} onChange={(e) => setDocTitle(e.target.value)} />
          <div className="hstack">
            <div style={{ flex: 1 }}>
              <label>Duration (min)</label>
              <input type="number" min={1} value={docDuration} onChange={(e) => setDocDuration(+e.target.value)} />
            </div>
            <div style={{ flex: 1 }}>
              <label>Batch (optional)</label>
              <input placeholder="e.g. Class 10A" value={docBatch} onChange={(e) => setDocBatch(e.target.value)} />
            </div>
          </div>
          <div>
            <label>PDF or image (max 25MB)</label>
            <input type="file" accept=".pdf,.png,.jpg,.jpeg" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </div>
          {error && <p className="error">{error}</p>}
          {info && <p style={{ color: 'var(--accent)', fontSize: 13 }}>{info}</p>}
          <button type="submit" disabled={saving}>{saving ? 'Uploading…' : 'Create test'}</button>
        </form>
      )}

      <h2>Existing tests</h2>
      {tests.length === 0 ? (
        <p className="empty">No tests created yet.</p>
      ) : (
        tests.map((t) => (
          <div key={t.id}>
            <div className="card row">
              <div>
                <div>{t.title}</div>
                <p style={{ margin: '2px 0 0' }}>
                  {t.duration_minutes} min
                  {t.batch ? ` · ${t.batch}` : ' · all students'}
                </p>
              </div>
              <div className="hstack">
                <span className="badge">{t.test_type === 'mcq_auto' ? 'MCQ' : 'Document'}</span>
                {t.test_type === 'mcq_auto' && (
                  <button className="btn-ghost btn-sm" onClick={() => handleToggleAnalytics(t.id)}>
                    {openAnalyticsFor === t.id ? 'Hide analytics' : 'View analytics'}
                  </button>
                )}
              </div>
            </div>
            {openAnalyticsFor === t.id && (
              <div className="card stack" style={{ marginTop: -4 }}>
                {analyticsLoading && <p style={{ margin: 0 }}>Loading…</p>}
                {analyticsError && <p className="error">{analyticsError}</p>}
                {analytics && !analyticsLoading && (
                  <>
                    <p style={{ margin: 0 }}>
                      {analytics.attempt_count} attempt(s) · avg score {analytics.average_score}
                      {' '}({analytics.average_score_pct}%) · {analytics.weak_question_count} weak question(s)
                    </p>
                    {analytics.questions.length === 0 ? (
                      <p className="empty">No submitted attempts yet.</p>
                    ) : (
                      analytics.questions.map((q) => (
                        <div className="row" key={q.question_id}>
                          <span>{q.text}</span>
                          <span className={`badge ${q.is_weak ? 'badge-muted' : ''}`}>
                            {q.correct_pct}% correct ({q.correct_count}/{q.attempts})
                          </span>
                        </div>
                      ))
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        ))
      )}
    </Layout>
  );
}