import { useEffect, useState } from 'react';
import { createStudent, listStudents, setParentPin, deleteStudent, setStudentPassword, studentAttendanceSummary, bulkImportStudents, batchAttendanceAnalytics, listBatches, createBatch, BatchOut } from '../api/client';
import Layout from '../components/Layout';

interface StudentOut {
  id: string; name: string; phone: string; parent_phone?: string | null;
  batch_id?: string | null; batch_name?: string | null; has_login: boolean; has_parent_login: boolean;
}

export default function ManageStudents() {
  const [students, setStudents] = useState<StudentOut[]>([]);
  const [attendance, setAttendance] = useState<Record<string, number>>({});
  const [batches, setBatches] = useState<BatchOut[]>([]);
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [parentPhone, setParentPhone] = useState('');
  const [batchId, setBatchId] = useState('');
  const [showNewBatch, setShowNewBatch] = useState(false);
  const [newBatchName, setNewBatchName] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  const [importFile, setImportFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<{
    created_count: number; skipped_count: number; skipped: { row: number; phone: string; reason: string }[];
  } | null>(null);
  const [importError, setImportError] = useState('');

  const [analyticsBatchId, setAnalyticsBatchId] = useState('');
  const [analytics, setAnalytics] = useState<{
    batch_id: string; batch_name: string; student_count: number; batch_average_pct: number;
    students: { student_id: string; student_name: string; attendance_pct: number; present_count: number; total_classes: number }[];
  } | null>(null);
  const [analyticsError, setAnalyticsError] = useState('');
  const [analyticsLoading, setAnalyticsLoading] = useState(false);

  function refresh() {
    listStudents().then((list) => {
      setStudents(list);
      // Fired per-student rather than a bulk endpoint - fine for typical coaching-centre
      // roster sizes, but revisit with a bulk /attendance/summary endpoint if this ever
      // needs to scale to hundreds of students on one screen.
      list.forEach((s: StudentOut) => {
        studentAttendanceSummary(s.id)
          .then((summary) => setAttendance((prev) => ({ ...prev, [s.id]: summary.attendance_pct })))
          .catch(() => {});
      });
    });
  }

  function refreshBatches() {
    listBatches().then(setBatches);
  }

  useEffect(() => { refresh(); refreshBatches(); }, []);

  async function handleCreateBatch() {
    if (!newBatchName.trim()) return;
    try {
      const b = await createBatch(newBatchName.trim());
      setBatches((prev) => [...prev, b].sort((a, c) => a.name.localeCompare(c.name)));
      setBatchId(b.id);
      setNewBatchName('');
      setShowNewBatch(false);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Could not create batch');
    }
  }

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setSaving(true);
    try {
      await createStudent({ name, phone, parent_phone: parentPhone || undefined, batch_id: batchId || undefined, password });
      setName(''); setPhone(''); setParentPhone(''); setBatchId(''); setPassword('');
      refresh();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Could not add student');
    } finally {
      setSaving(false);
    }
  }

  async function handleImport(e: React.FormEvent) {
    e.preventDefault();
    if (!importFile) return;
    setImportError('');
    setImporting(true);
    try {
      const result = await bulkImportStudents(importFile);
      setImportResult(result);
      setImportFile(null);
      refresh();
      refreshBatches(); // a CSV batch column can create new batches on the fly
    } catch (err: any) {
      setImportError(err?.response?.data?.detail || 'Could not import CSV');
    } finally {
      setImporting(false);
    }
  }

  async function handleAnalytics(e: React.FormEvent) {
    e.preventDefault();
    if (!analyticsBatchId) return;
    setAnalyticsError('');
    setAnalyticsLoading(true);
    setAnalytics(null);
    try {
      setAnalytics(await batchAttendanceAnalytics(analyticsBatchId));
    } catch (err: any) {
      setAnalyticsError(err?.response?.data?.detail || 'Could not load analytics');
    } finally {
      setAnalyticsLoading(false);
    }
  }

  function apiMsg(err: any, fallback: string) {
    const d = err?.response?.data?.detail;
    return typeof d === 'string' ? d : fallback;
  }

  async function handleDelete(id: string, studentName: string) {
    if (!confirm(`Delete ${studentName}? This also removes their attendance and test attempts.`)) return;
    try { await deleteStudent(id); setError(''); refresh(); }
    catch (err: any) { setError(apiMsg(err, 'Could not delete student')); }
  }

  async function handleResetPassword(id: string) {
    const pw = prompt('New login PIN for this student (min 4 characters):');
    if (!pw) return;
    try { await setStudentPassword(id, pw); setError(''); alert('PIN updated.'); }
    catch (err: any) { setError(apiMsg(err, 'Could not update PIN')); }
  }

  async function handleParentPin(id: string) {
    const pin = prompt('Set a parent PIN for this student\u2019s parent view:');
    if (!pin) return;
    await setParentPin(id, pin);
    refresh();
  }

  return (
    <Layout>
      <h1>Students</h1>

      <form onSubmit={handleAdd} className="card stack">
        <div className="hstack">
          <input required placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} style={{ flex: 2 }} />
          <input required placeholder="Phone" value={phone} onChange={(e) => setPhone(e.target.value)} style={{ flex: 1 }} />
        </div>
        <div className="hstack" style={{ alignItems: 'center' }}>
          <select value={batchId} onChange={(e) => setBatchId(e.target.value)} style={{ flex: 1 }}>
            <option value="">No batch</option>
            {batches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
          <button type="button" className="btn-ghost btn-sm" onClick={() => setShowNewBatch((v) => !v)}>+ New batch</button>
          <input placeholder="Parent phone (optional)" value={parentPhone} onChange={(e) => setParentPhone(e.target.value)} style={{ flex: 1 }} />
        </div>
        {showNewBatch && (
          <div className="hstack">
            <input placeholder="e.g. Class 10 - Batch A" value={newBatchName} onChange={(e) => setNewBatchName(e.target.value)} />
            <button type="button" className="btn-sm" onClick={handleCreateBatch}>Create</button>
          </div>
        )}
        <input required placeholder="Login PIN for student" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={saving}>{saving ? 'Adding…' : 'Add student'}</button>
      </form>

      <form onSubmit={handleImport} className="card stack">
        <div className="hstack">
          <input
            type="file" accept=".csv,text/csv"
            onChange={(e) => setImportFile(e.target.files?.[0] || null)}
          />
          <button type="submit" disabled={importing || !importFile}>
            {importing ? 'Importing…' : 'Bulk import CSV'}
          </button>
        </div>
        <p style={{ margin: 0, color: 'var(--muted)', fontSize: 13 }}>
          Columns: name, phone, parent_phone (optional), batch (optional — a batch name; a
          new batch is created automatically if it doesn't match one you already have),
          password (optional — defaults to last 4 digits of phone).
        </p>
        {importError && <p className="error">{importError}</p>}
        {importResult && (
          <p style={{ margin: 0 }}>
            Added {importResult.created_count}, skipped {importResult.skipped_count}.
            {importResult.skipped.length > 0 && (
              <span style={{ display: 'block', color: 'var(--muted)', fontSize: 13 }}>
                {importResult.skipped.map((s) => `Row ${s.row} (${s.phone}): ${s.reason}`).join(' · ')}
              </span>
            )}
          </p>
        )}
      </form>

      <h2>Roster ({students.length})</h2>
      {students.length === 0 ? (
        <p className="empty">No students yet.</p>
      ) : (
        students.map((s) => (
          <div className="card row" key={s.id}>
            <div>
              <div>{s.name} <span style={{ color: 'var(--muted)', fontSize: 13 }}>{s.phone}</span></div>
              <p style={{ margin: '2px 0 0' }}>{s.batch_name || 'No batch'}</p>
            </div>
            <div className="hstack">
              {attendance[s.id] !== undefined && (
                <span className={`badge ${attendance[s.id] < 75 ? 'badge-muted' : ''}`}>
                  {attendance[s.id]}% attendance
                </span>
              )}
              <span className={`badge ${s.has_login ? '' : 'badge-muted'}`}>{s.has_login ? 'login active' : 'no login'}</span>
              <button className="btn-ghost btn-sm" onClick={() => handleParentPin(s.id)}>
                {s.has_parent_login ? 'Reset parent PIN' : 'Set parent PIN'}
              </button>
              <button className="btn-ghost btn-sm" onClick={() => handleResetPassword(s.id)}>Reset PIN</button>
              <button className="btn-ghost btn-sm" onClick={() => handleDelete(s.id, s.name)}>Delete</button>
            </div>
          </div>
        ))
      )}
      <h2>Batch attendance analytics</h2>
      <form onSubmit={handleAnalytics} className="card hstack">
        <select value={analyticsBatchId} onChange={(e) => setAnalyticsBatchId(e.target.value)} style={{ flex: 1 }}>
          <option value="">Select a batch…</option>
          {batches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
        </select>
        <button type="submit" disabled={analyticsLoading || !analyticsBatchId}>
          {analyticsLoading ? 'Loading…' : 'View'}
        </button>
      </form>
      {analyticsError && <p className="error">{analyticsError}</p>}
      {analytics && (
        <div className="card stack">
          <p style={{ margin: 0 }}>
            {analytics.batch_name} — {analytics.student_count} student(s) · batch average {analytics.batch_average_pct}%
          </p>
          {analytics.students.map((row) => (
            <div className="row" key={row.student_id}>
              <span>{row.student_name}</span>
              <span className={`badge ${row.attendance_pct < 75 ? 'badge-muted' : ''}`}>
                {row.attendance_pct}% ({row.present_count}/{row.total_classes})
              </span>
            </div>
          ))}
        </div>
      )}
    </Layout>
  );
}
