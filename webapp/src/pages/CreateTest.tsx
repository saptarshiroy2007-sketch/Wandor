import { useEffect, useState } from 'react';
import { createMcqTest, createDocumentTest, uploadTestDocument, listTests, testAnalytics, listUngradedAttempts, gradeAttempt, listBatches, createBatch, QuestionIn, TestAttemptOut, BatchOut } from '../api/client';
import Layout from '../components/Layout';

interface TestOut {
  id: string; title: string; test_type: string; duration_minutes: number;
  batch_id?: string | null; batch_name?: string | null;
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
  const [batchId, setBatchId] = useState('');
  const [questions, setQuestions] = useState<QuestionIn[]>([EMPTY_QUESTION()]);

  // Document fields
  const [docTitle, setDocTitle] = useState('');
  const [docDuration, setDocDuration] = useState(30);
  const [docBatchId, setDocBatchId] = useState('');
  const [file, setFile] = useState<File | null>(null);

  // Batches (shared picker across MCQ/document forms)
  const [batches, setBatches] = useState<BatchOut[]>([]);
  const [showNewBatch, setShowNewBatch] = useState(false);
  const [newBatchName, setNewBatchName] = useState('');

  // Analytics
  const [openAnalyticsFor, setOpenAnalyticsFor] = useState<string | null>(null);
  const [analyticsLoading, setAnalyticsLoading] = useState(false);
  const [analyticsError, setAnalyticsError] = useState('');
  const [analytics, setAnalytics] = useState<{
    attempt_count: number; average_score: number; average_score_pct: number; weak_question_count: number;
    questions: { question_id: string; text: string; attempts: number; correct_count: number; correct_pct: number; is_weak: boolean }[];
  } | null>(null);

  // Grading (document_locked tests)
  const [openGradingFor, setOpenGradingFor] = useState<string | null>(null);
  const [gradingLoading, setGradingLoading] = useState(false);
  const [gradingError, setGradingError] = useState('');
  const [ungraded, setUngraded] = useState<TestAttemptOut[]>([]);
  const [gradeInputs, setGradeInputs] = useState<Record<string, { score: string; max_score: string }>>({});
  const [publishingId, setPublishingId] = useState<string | null>(null);
  const [publishError, setPublishError] = useState<Record<string, string>>({});

  function refresh() { listTests().then(setTests); }
  useEffect(refresh, []);
  useEffect(() => { listBatches().then(setBatches); }, []);

  async function handleCreateBatch(applyTo: 'mcq' | 'document') {
    if (!newBatchName.trim()) return;
    try {
      const b = await createBatch(newBatchName.trim());
      setBatches((prev) => [...prev, b].sort((a, c) => a.name.localeCompare(c.name)));
      if (applyTo === 'mcq') setBatchId(b.id); else setDocBatchId(b.id);
      setNewBatchName('');
      setShowNewBatch(false);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Could not create batch');
    }
  }

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
      const res = await createMcqTest({ title, duration_minutes: duration, batch_id: batchId || undefined, questions });
      setInfo(`Created — ${res.questions_created} question(s) saved.`);
      setTitle(''); setBatchId(''); setQuestions([EMPTY_QUESTION()]);
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
      await createDocumentTest({ title: docTitle, document_url: uploaded.url, duration_minutes: docDuration, batch_id: docBatchId || undefined });
      setInfo('Created.');
      setDocTitle(''); setDocBatchId(''); setFile(null);
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

  async function handleToggleGrading(testId: string) {
    if (openGradingFor === testId) { setOpenGradingFor(null); return; }
    setOpenGradingFor(testId); setUngraded([]); setGradingError(''); setGradingLoading(true);
    try {
      const attempts = await listUngradedAttempts(testId);
      setUngraded(attempts);
      setGradeInputs(Object.fromEntries(attempts.map((a) => [a.id, { score: '', max_score: '' }])));
    } catch (err: any) {
      setGradingError(err?.response?.data?.detail || 'Could not load submissions');
    } finally {
      setGradingLoading(false);
    }
  }

  async function handlePublishGrade(attemptId: string) {
    const input = gradeInputs[attemptId];
    const score = Number(input?.score);
    const maxScore = Number(input?.max_score);
    setPublishError((e) => ({ ...e, [attemptId]: '' }));
    if (!input?.score.trim() || !input?.max_score.trim() || isNaN(score) || isNaN(maxScore)) {
      setPublishError((e) => ({ ...e, [attemptId]: 'Enter both score and max score' }));
      return;
    }
    if (maxScore <= 0 || score < 0 || score > maxScore) {
      setPublishError((e) => ({ ...e, [attemptId]: 'Score must be between 0 and max score' }));
      return;
    }
    setPublishingId(attemptId);
    try {
      await gradeAttempt(attemptId, score, maxScore);
      // Graded attempts drop off the "ungraded" worklist - the parent/student already
      // got their WhatsApp ping from the backend, nothing more to show here.
      setUngraded((list) => list.filter((a) => a.id !== attemptId));
    } catch (err: any) {
      setPublishError((e) => ({ ...e, [attemptId]: err?.response?.data?.detail || 'Could not publish grade' }));
    } finally {
      setPublishingId(null);
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
              <div className="hstack" style={{ alignItems: 'center' }}>
                <select value={batchId} onChange={(e) => setBatchId(e.target.value)} style={{ flex: 1 }}>
                  <option value="">All students</option>
                  {batches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
                </select>
                <button type="button" className="btn-ghost btn-sm" onClick={() => setShowNewBatch((v) => !v)}>+ New</button>
              </div>
              {showNewBatch && (
                <div className="hstack" style={{ marginTop: 6 }}>
                  <input placeholder="e.g. Class 10A" value={newBatchName} onChange={(e) => setNewBatchName(e.target.value)} />
                  <button type="button" className="btn-sm" onClick={() => handleCreateBatch('mcq')}>Create</button>
                </div>
              )}
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
              <div className="hstack" style={{ alignItems: 'center' }}>
                <select value={docBatchId} onChange={(e) => setDocBatchId(e.target.value)} style={{ flex: 1 }}>
                  <option value="">All students</option>
                  {batches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
                </select>
                <button type="button" className="btn-ghost btn-sm" onClick={() => setShowNewBatch((v) => !v)}>+ New</button>
              </div>
              {showNewBatch && (
                <div className="hstack" style={{ marginTop: 6 }}>
                  <input placeholder="e.g. Class 10A" value={newBatchName} onChange={(e) => setNewBatchName(e.target.value)} />
                  <button type="button" className="btn-sm" onClick={() => handleCreateBatch('document')}>Create</button>
                </div>
              )}
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
                  {t.batch_name ? ` · ${t.batch_name}` : ' · all students'}
                </p>
              </div>
              <div className="hstack">
                <span className="badge">{t.test_type === 'mcq_auto' ? 'MCQ' : 'Document'}</span>
                {t.test_type === 'mcq_auto' && (
                  <button className="btn-ghost btn-sm" onClick={() => handleToggleAnalytics(t.id)}>
                    {openAnalyticsFor === t.id ? 'Hide analytics' : 'View analytics'}
                  </button>
                )}
                {t.test_type === 'document_locked' && (
                  <button className="btn-ghost btn-sm" onClick={() => handleToggleGrading(t.id)}>
                    {openGradingFor === t.id ? 'Hide grading' : 'Grade submissions'}
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
            {openGradingFor === t.id && (
              <div className="card stack" style={{ marginTop: -4 }}>
                {gradingLoading && <p style={{ margin: 0 }}>Loading…</p>}
                {gradingError && <p className="error">{gradingError}</p>}
                {!gradingLoading && !gradingError && ungraded.length === 0 && (
                  <p className="empty">Nothing waiting to be graded — every submission's marked.</p>
                )}
                {!gradingLoading && ungraded.map((a) => (
                  <div key={a.id} className="card stack" style={{ marginBottom: 8 }}>
                    <div className="row">
                      <span>Submitted {new Date(a.submitted_at as string).toLocaleString()}</span>
                      {a.is_flagged && <span className="badge badge-muted">Flagged ×{a.flag_count}</span>}
                    </div>
                    <div className="hstack" style={{ alignItems: 'center', gap: 8 }}>
                      <input
                        type="number" min={0} placeholder="Score" style={{ width: 90 }}
                        value={gradeInputs[a.id]?.score ?? ''}
                        onChange={(e) => setGradeInputs((g) => ({ ...g, [a.id]: { ...g[a.id], score: e.target.value } }))}
                      />
                      <span>/</span>
                      <input
                        type="number" min={1} placeholder="Max score" style={{ width: 90 }}
                        value={gradeInputs[a.id]?.max_score ?? ''}
                        onChange={(e) => setGradeInputs((g) => ({ ...g, [a.id]: { ...g[a.id], max_score: e.target.value } }))}
                      />
                      <button
                        className="btn-sm" disabled={publishingId === a.id}
                        onClick={() => handlePublishGrade(a.id)}
                      >
                        {publishingId === a.id ? 'Publishing…' : 'Publish grade'}
                      </button>
                    </div>
                    {publishError[a.id] && <p className="error" style={{ margin: 0 }}>{publishError[a.id]}</p>}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))
      )}
    </Layout>
  );
}