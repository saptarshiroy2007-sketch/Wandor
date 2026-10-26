import { useEffect, useState } from 'react';
import { getInstitute, updateInstitute, listInstituteTeachers, createTeacher, deleteTeacher, setTeacherBatches, listInstituteBatches, createInstituteBatch, BatchOut } from '../api/client';
import { Link } from 'react-router-dom';
import Layout from '../components/Layout';

interface InstituteOut {
  id: string; name: string; owner_phone: string; plan: string; created_at: string;
}

interface TeacherOut {
  id: string; name: string; phone: string; is_owner: boolean; batches?: BatchOut[];
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
  const [isOwner, setIsOwner] = useState(false);
  const [newBatchIds, setNewBatchIds] = useState<string[]>([]);
  const [batches, setBatches] = useState<BatchOut[]>([]);
  const [batchName, setBatchName] = useState('');
  const [batchError, setBatchError] = useState('');
  const [listError, setListError] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editIds, setEditIds] = useState<string[]>([]);

  const msg = (err: any, fb: string) => {
    const d = err?.response?.data?.detail;
    return typeof d === 'string' ? d : Array.isArray(d) ? d.map((x: any) => x.msg).join('; ') : fb;
  };
  const toggle = (ids: string[], id: string) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]);

  function refresh() {
    getInstitute().then((inst) => { setInstitute(inst); setNameDraft(inst.name); });
    listInstituteTeachers().then(setTeachers);
    listInstituteBatches().then(setBatches).catch(() => {});
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
      await createTeacher({ name, phone, password, is_owner: isOwner, batch_ids: isOwner ? [] : newBatchIds });
      setName(''); setPhone(''); setPassword(''); setIsOwner(false); setNewBatchIds([]);
      refresh();
    } catch (err: any) {
      setError(msg(err, 'Could not add teacher'));
    } finally {
      setSaving(false);
    }
  }

  async function handleRemoveTeacher(id: string) {
    if (!confirm('Remove this teacher?')) return;
    setListError('');
    try { await deleteTeacher(id); } catch (err: any) { setListError(msg(err, 'Could not remove teacher')); }
    refresh();
  }

  async function handleAddBatch(e: React.FormEvent) {
    e.preventDefault();
    setBatchError('');
    try { await createInstituteBatch(batchName.trim()); setBatchName(''); refresh(); }
    catch (err: any) { setBatchError(msg(err, 'Could not create batch')); }
  }

  async function handleSaveBatches(teacherId: string) {
    setListError('');
    try { await setTeacherBatches(teacherId, editIds); setEditingId(null); refresh(); }
    catch (err: any) { setListError(msg(err, 'Could not update batches')); }
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
            Owner phone: {institute.owner_phone} · Plan: <span className="badge">{institute.plan}</span> <Link to="/billing">Manage plan</Link>
          </p>
          <button type="submit" disabled={savingName || nameDraft === institute.name}>
            {savingName ? 'Saving…' : 'Save'}
          </button>
        </form>
      )}

      <h2>Batches ({batches.length})</h2>
      <form onSubmit={handleAddBatch} className="card hstack">
        <input required maxLength={100} placeholder="New batch name" value={batchName} onChange={(e) => setBatchName(e.target.value)} style={{ flex: 1 }} />
        <button type="submit">Add batch</button>
      </form>
      {batchError && <p className="error">{batchError}</p>}
      {batches.length > 0 && <p style={{ margin: '0 0 8px' }}>{batches.map((b) => b.name).join(' · ')}</p>}

      <h2>Add a teacher</h2>
      <form onSubmit={handleAddTeacher} className="card stack">
        <div className="hstack">
          <input required placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} style={{ flex: 2 }} />
          <input required placeholder="Phone" value={phone} onChange={(e) => setPhone(e.target.value)} style={{ flex: 1 }} />
        </div>
        <input required placeholder="Login password for teacher" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        <label className="omr-option" style={{ padding: 0 }}>
          <input type="checkbox" checked={isOwner} onChange={(e) => setIsOwner(e.target.checked)} />
          <span className="omr-bubble square" /> Owner (can manage every batch)
        </label>
        {!isOwner && batches.length > 0 && (
          <div>
            <label>Batches this teacher can manage</label>
            {batches.map((b) => (
              <label key={b.id} className="omr-option" style={{ padding: '4px 0' }}>
                <input type="checkbox" checked={newBatchIds.includes(b.id)} onChange={() => setNewBatchIds(toggle(newBatchIds, b.id))} />
                <span className="omr-bubble square" /> {b.name}
              </label>
            ))}
          </div>
        )}
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={saving}>{saving ? 'Adding…' : 'Add teacher'}</button>
      </form>

      <h2>Teachers ({teachers.length})</h2>
      {listError && <p className="error">{listError}</p>}
      {teachers.length === 0 ? (
        <p className="empty">No teachers yet.</p>
      ) : (
        teachers.map((t) => (
          <div className="card row" key={t.id}>
            <div>
              <div>{t.name} <span style={{ color: 'var(--muted)', fontSize: 13 }}>{t.phone}</span></div>
              {t.is_owner ? <span className="badge">owner</span> : (
                <p style={{ margin: '2px 0 0', fontSize: 13 }}>
                  Batches: {t.batches && t.batches.length ? t.batches.map((b) => b.name).join(', ') : 'none assigned'}
                </p>
              )}
              {editingId === t.id && (
                <div style={{ marginTop: 8 }}>
                  {batches.map((b) => (
                    <label key={b.id} className="omr-option" style={{ padding: '4px 0' }}>
                      <input type="checkbox" checked={editIds.includes(b.id)} onChange={() => setEditIds(toggle(editIds, b.id))} />
                      <span className="omr-bubble square" /> {b.name}
                    </label>
                  ))}
                  <div className="hstack" style={{ marginTop: 6 }}>
                    <button className="btn-sm" onClick={() => handleSaveBatches(t.id)}>Save</button>
                    <button className="btn-ghost btn-sm" onClick={() => setEditingId(null)}>Cancel</button>
                  </div>
                </div>
              )}
            </div>
            <div className="hstack">
              {!t.is_owner && editingId !== t.id && (
                <button className="btn-ghost btn-sm" onClick={() => { setEditingId(t.id); setEditIds((t.batches || []).map((b) => b.id)); }}>Assign batches</button>
              )}
              <button className="btn-ghost btn-sm" onClick={() => handleRemoveTeacher(t.id)}>Remove</button>
            </div>
          </div>
        ))
      )}
    </Layout>
  );
}
