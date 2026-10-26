import { useEffect, useState } from 'react';
import { listInstituteStudents, createInstituteStudent, deleteInstituteStudent, listInstituteBatches, BatchOut } from '../api/client';
import Layout from '../components/Layout';

interface StudentRow { id: string; name: string; phone: string; batch_id?: string | null; batch_name?: string | null; }

const msg = (err: any, fb: string) => {
  const d = err?.response?.data?.detail;
  return typeof d === 'string' ? d : Array.isArray(d) ? d.map((x: any) => x.msg).join('; ') : fb;
};

export default function InstituteStudents() {
  const [students, setStudents] = useState<StudentRow[]>([]);
  const [batches, setBatches] = useState<BatchOut[]>([]);
  const [filter, setFilter] = useState('');
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [parentPhone, setParentPhone] = useState('');
  const [batchId, setBatchId] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  function refresh() {
    listInstituteStudents(filter || undefined).then(setStudents).catch((e) => setError(msg(e, 'Could not load students')));
  }
  useEffect(() => { listInstituteBatches().then(setBatches).catch(() => {}); }, []);
  useEffect(refresh, [filter]);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setSaving(true);
    try {
      await createInstituteStudent({ name, phone, parent_phone: parentPhone || undefined, batch_id: batchId || undefined, password });
      setName(''); setPhone(''); setParentPhone(''); setPassword('');
      refresh();
    } catch (err: any) {
      setError(msg(err, 'Could not add student'));
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(s: StudentRow) {
    if (!confirm(`Delete ${s.name}? This also removes their attendance and test attempts.`)) return;
    try { await deleteInstituteStudent(s.id); setError(''); refresh(); }
    catch (err: any) { setError(msg(err, 'Could not delete student')); }
  }

  return (
    <Layout>
      <h1>Students</h1>

      <form onSubmit={handleAdd} className="card stack">
        <div className="hstack">
          <input required maxLength={200} placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} style={{ flex: 2 }} />
          <input required placeholder="Phone" value={phone} onChange={(e) => setPhone(e.target.value)} style={{ flex: 1 }} />
        </div>
        <div className="hstack">
          <input placeholder="Parent phone (optional)" value={parentPhone} onChange={(e) => setParentPhone(e.target.value)} style={{ flex: 1 }} />
          <select value={batchId} onChange={(e) => setBatchId(e.target.value)} style={{ flex: 1 }}>
            <option value="">No batch</option>
            {batches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </div>
        <input required minLength={4} placeholder="Login PIN for student (min 4)" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={saving}>{saving ? 'Adding…' : 'Add student'}</button>
      </form>

      <div className="hstack" style={{ margin: '12px 0' }}>
        <h2 style={{ margin: 0, flex: 1 }}>All students ({students.length})</h2>
        <select value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">All batches</option>
          {batches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
        </select>
      </div>
      {students.length === 0 ? (
        <p className="empty">No students yet.</p>
      ) : (
        students.map((s) => (
          <div className="card row" key={s.id}>
            <div>
              <div>{s.name} <span style={{ color: 'var(--muted)', fontSize: 13 }}>{s.phone}</span></div>
              <p style={{ margin: '2px 0 0', fontSize: 13 }}>{s.batch_name || 'No batch'}</p>
            </div>
            <button className="btn-ghost btn-sm" onClick={() => handleDelete(s)}>Delete</button>
          </div>
        ))
      )}
    </Layout>
  );
}
