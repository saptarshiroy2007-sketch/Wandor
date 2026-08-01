import { useEffect, useState } from 'react';
import { createMcqTest, createDocumentTest, uploadTestDocument, listTests, testAnalytics } from '../api/client';
import Layout from '../components/Layout';

interface TestOut {
  id: string; title: string; test_type: string; duration_minutes: number; topic?: string | null;
}

export default function CreateTest() {
  const [mode, setMode] = useState<'mcq' | 'document'>('mcq');
  const [tests, setTests] = useState<TestOut[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [info, setInfo] = useState('');

  // mcq fields
  const [title, setTitle] = useState('');
  const [topic, setTopic] = useState('');
  const [numQuestions, setNumQuestions] = useState(10);
  const [duration, setDuration] = useState(30);

  // document fields
  const [docTitle, setDocTitle] = useState('');
  const [docDuration, setDocDuration] = useState(30);
  const [file, setFile] = useState<File | null>(null);

  // analytics
  const [openAnalyticsFor, setOpenAnalyticsFor] = useState<string | null>(null);
  const [analyticsLoading, setAnalyticsLoading] = useState(false);
  const [analyticsError, setAnalyticsError] = useState('');
  const [analytics, setAnalytics] = useState<{
    attempt_count: number; average_score: number; average_score_pct: number; weak_question_count: number;
    questions: { question_id: string; text: string; attempts: number; correct_count: number; correct_pct: number; is_weak: boolean }[];
  } | null>(null);

  function refresh() {
    listTests().then(setTests);
  }

  useEffect(refresh, []);

  async function handleMcqSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(''); setInfo(''); setSaving(true);
    try {
      const res = await createMcqTest({ title, topic, num_questions: numQuestions, duration_minutes: duration });
      setInfo(`Created — ${res.questions_generated} questions generated.`);
      setTitle(''); setTopic('');
      refresh();
    } catch {
      setError('Could not create test');
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
      await createDocumentTest({ title: docTitle, document_url: uploaded.url, duration_minutes: docDuration });
      setInfo('Created.');
      setDocTitle(''); setFile(null);
      refresh();
    } catch {
      setError('Could not create test');
    } finally {
      setSaving(false);
    }
  }

  async function handleToggleAnalytics(testId: string) {
    if (openAnalyticsFor === testId) {
      setOpenAnalyticsFor(null);
      return;
    }
    setOpenAnalyticsFor(testId);
    setAnalytics(null);
    setAnalyticsError('');
    setAnalyticsLoading(true);
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
        <button className={mode === 'mcq' ? '' : 'btn-ghost'} onClick={() => setMode('mcq')}>MCQ (auto-generated)</button>
        <button className={mode === 'document' ? '' : 'btn-ghost'} onClick={() => setMode('document')}>Upload document</button>
      </div>

      {mode === 'mcq' ? (
        <form onSubmit={handleMcqSubmit} className="card stack">
          <input required placeholder="Title" value={title} onChange={(e) => setTitle(e.target.value)} />
          <input required placeholder="Topic (e.g. Photosynthesis)" value={topic} onChange={(e) => setTopic(e.target.value)} />
          <div className="hstack">
            <div style={{ flex: 1 }}>
              <label>Questions</label>
              <input type="number" min={1} max={50} value={numQuestions} onChange={(e) => setNumQuestions(+e.target.value)} />
            </div>
            <div style={{ flex: 1 }}>
              <label>Duration (min)</label>
              <input type="number" min={1} value={duration} onChange={(e) => setDuration(+e.target.value)} />
            </div>
          </div>
          {error && <p className="error">{error}</p>}
          {info && <p style={{ color: 'var(--accent)', fontSize: 13 }}>{info}</p>}
          <button type="submit" disabled={saving}>{saving ? 'Generating…' : 'Create test'}</button>
        </form>
      ) : (
        <form onSubmit={handleDocSubmit} className="card stack">
          <input required placeholder="Title" value={docTitle} onChange={(e) => setDocTitle(e.target.value)} />
          <div>
            <label>Duration (min)</label>
            <input type="number" min={1} value={docDuration} onChange={(e) => setDocDuration(+e.target.value)} />
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
                <p style={{ margin: '2px 0 0' }}>{t.duration_minutes} min{t.topic ? ` · ${t.topic}` : ''}</p>
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
