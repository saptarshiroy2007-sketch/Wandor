import { useEffect, useState } from 'react';
import { getInstitute, updateInstitute, listInstituteTeachers, createTeacher, deleteTeacher } from '../api/client';
import Layout from '../components/Layout';

interface InstituteOut {
  id: string; name: string; owner_phone: string; plan: string; created_at: string;
}

interface TeacherOut {
  id: string; name: string; phone: string; is_owner: boolean;
}

export default function InstituteDashboard() {
  const [institute, setInstitute] = useState<InstituteOut | null>(null);
  const [nameDraft, setNameDraft] = useState('');
  const [savingName, setSavingName] = useState(false);

  const [teachers, setTeachers] = useState<TeacherOut[]>([]);
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  function refresh() {
    getInstitute().then((inst) => { setInstitute(inst); setNameDraft(inst.name); });
    listInstituteTeachers().then(setTeachers);
  }

  useEffect(refresh, []);

  async function handleSaveName(e: React.FormEvent) {
    e.preventDefault();
    setSavingName(true);
    try {
      const updated = await updateInstitute(nameDraft);
      setInstitute(updated);
    } finally {
      setSavingName(false);
    }
  }

  async function handleAddTeacher(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setSaving(true);
    try {
      await createTeacher({ name, phone, password });
      setName(''); setPhone(''); setPassword('');
      refresh();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Could not add teacher');
    } finally {
      setSaving(false);
    }
  }

  async function handleRemoveTeacher(id: string) {
    if (!confirm('Remove this teacher?')) return;
    await deleteTeacher(id);
    refresh();
  }

  return (
    <Layout>
      <h1>Institute</h1>

      {institute && (
        <form onSubmit={handleSaveName} className="card stack">
          <div>
            <label>Institute name</label>
            <input value={nameDraft} onChange={(e) => setNameDraft(e.target.value)} />
          </div>
          <p style={{ margin: 0 }}>
            Owner phone: {institute.owner_phone} · Plan: <span className="badge">{institute.plan}</span>
          </p>
          <button type="submit" disabled={savingName || nameDraft === institute.name}>
            {savingName ? 'Saving…' : 'Save'}
          </button>
        </form>
      )}

      <h2>Add a teacher</h2>
      <form onSubmit={handleAddTeacher} className="card stack">
        <div className="hstack">
          <input required placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} style={{ flex: 2 }} />
          <input required placeholder="Phone" value={phone} onChange={(e) => setPhone(e.target.value)} style={{ flex: 1 }} />
        </div>
        <input required placeholder="Login password for teacher" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={saving}>{saving ? 'Adding…' : 'Add teacher'}</button>
      </form>

      <h2>Teachers ({teachers.length})</h2>
      {teachers.length === 0 ? (
        <p className="empty">No teachers yet.</p>
      ) : (
        teachers.map((t) => (
          <div className="card row" key={t.id}>
            <div>
              <div>{t.name} <span style={{ color: 'var(--muted)', fontSize: 13 }}>{t.phone}</span></div>
              {t.is_owner && <span className="badge">owner</span>}
            </div>
            <button className="btn-ghost btn-sm" onClick={() => handleRemoveTeacher(t.id)}>Remove</button>
          </div>
        ))
      )}
    </Layout>
  );
}
