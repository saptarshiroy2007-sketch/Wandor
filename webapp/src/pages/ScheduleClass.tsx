import { useEffect, useState } from 'react';
import { scheduleClass, listClasses, cancelClass, rescheduleClass, listBatches, createBatch, toLocalInput, BatchOut } from '../api/client';
import Layout from '../components/Layout';

interface ClassSession {
  id: string;
  batch_id: string;
  batch_name: string;
  subject: string;
  start_time: string;
  end_time: string;
  status: 'scheduled' | 'cancelled' | 'completed';
}

export default function ScheduleClass() {
  const [batches, setBatches] = useState<BatchOut[]>([]);
  const [batchId, setBatchId] = useState('');
  const [showNewBatch, setShowNewBatch] = useState(false);
  const [newBatchName, setNewBatchName] = useState('');
  const [subject, setSubject] = useState('');
  const [startTime, setStartTime] = useState('');
  const [endTime, setEndTime] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const [classes, setClasses] = useState<ClassSession[]>([]);
  const [reschedulingId, setReschedulingId] = useState<string | null>(null);
  const [newStart, setNewStart] = useState('');
  const [newEnd, setNewEnd] = useState('');

  function refresh() {
    listClasses().then(setClasses);
  }

  function refreshBatches() {
    listBatches().then(setBatches);
  }

  useEffect(() => {
    refresh();
    refreshBatches();
  }, []);

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

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    if (!batchId) {
      setError('Pick a batch first');
      return;
    }
    if (!subject.trim()) { setError('Enter a subject'); return; }
    if (!startTime || !endTime) { setError('Pick a start and end time'); return; }
    if (new Date(endTime) <= new Date(startTime)) { setError('End time must be after the start time'); return; }
    setSaving(true);
    try {
      await scheduleClass({
        batch_id: batchId, subject,
        start_time: new Date(startTime).toISOString(),
        end_time: new Date(endTime).toISOString(),
      });
      setSubject(''); setStartTime(''); setEndTime('');
      refresh();
    } catch (err: any) {
      const d = err?.response?.data?.detail;
      setError(typeof d === 'string' ? d : Array.isArray(d) ? d.map((x: any) => x.msg).join('; ') : 'Could not schedule class');
    } finally {
      setSaving(false);
    }
  }

  async function handleCancel(cls: ClassSession) {
    const reason = window.prompt(`Cancel ${cls.subject} for ${cls.batch_name}? Reason (optional):`);
    if (reason === null) return; // they hit cancel on the prompt itself
    try { await cancelClass(cls.id, reason || undefined); } catch (err: any) {
      const d = err?.response?.data?.detail;
      setError(typeof d === 'string' ? d : 'Could not cancel');
    }
    refresh();
  }

  function openReschedule(cls: ClassSession) {
    setReschedulingId(cls.id);
    setNewStart(toLocalInput(cls.start_time));
    setNewEnd(toLocalInput(cls.end_time));
  }

  async function handleReschedule(cls: ClassSession) {
    setError('');
    if (!newStart || !newEnd || new Date(newEnd) <= new Date(newStart)) { setError('End time must be after the start time'); return; }
    try {
      await rescheduleClass(cls.id, {
        start_time: new Date(newStart).toISOString(),
        end_time: new Date(newEnd).toISOString(),
      });
      setReschedulingId(null);
      refresh();
    } catch (err: any) {
      const d = err?.response?.data?.detail;
      setError(typeof d === 'string' ? d : 'Could not reschedule');
    }
  }

  const upcoming = classes.filter((c) => c.status === 'scheduled');

  return (
    <Layout>
      <h1>Schedule a class</h1>
      <form onSubmit={handleSubmit} className="card stack">
        <div>
          <label>Batch</label>
          {batches.length === 0 && !showNewBatch ? (
            <p style={{ margin: '4px 0' }}>
              No batches yet. <button type="button" className="btn-ghost btn-sm" onClick={() => setShowNewBatch(true)}>Create one</button>
            </p>
          ) : (
            <div className="hstack" style={{ alignItems: 'center' }}>
              <select value={batchId} onChange={(e) => setBatchId(e.target.value)}>
                <option value="">Select a batch…</option>
                {batches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
              <button type="button" className="btn-ghost btn-sm" onClick={() => setShowNewBatch((v) => !v)}>+ New batch</button>
            </div>
          )}
          {showNewBatch && (
            <div className="hstack" style={{ marginTop: 6 }}>
              <input placeholder="e.g. Class 10 - Batch A" value={newBatchName} onChange={(e) => setNewBatchName(e.target.value)} />
              <button type="button" className="btn-sm" onClick={handleCreateBatch}>Create</button>
            </div>
          )}
        </div>
        <div>
          <label>Subject</label>
          <input required maxLength={200} placeholder="Subject" value={subject} onChange={(e) => setSubject(e.target.value)} />
        </div>
        <div>
          <label>Start</label>
          <input required type="datetime-local" value={startTime} onChange={(e) => setStartTime(e.target.value)} />
        </div>
        <div>
          <label>End</label>
          <input required type="datetime-local" value={endTime} onChange={(e) => setEndTime(e.target.value)} />
        </div>
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={saving}>{saving ? 'Scheduling…' : 'Schedule & notify batch'}</button>
      </form>

      <h2>Upcoming classes</h2>
      {upcoming.length === 0 ? (
        <p className="empty">No upcoming classes.</p>
      ) : (
        <div className="stack">
          {upcoming.map((cls) => (
            <div key={cls.id} className="card stack">
              <div className="row">
                <div>
                  <strong>{cls.subject}</strong> — {cls.batch_name}
                  <p style={{ margin: '2px 0 0' }}>{new Date(cls.start_time).toLocaleString()}</p>
                </div>
                <div className="hstack">
                  <button className="btn-ghost btn-sm" onClick={() => openReschedule(cls)}>Reschedule</button>
                  <button className="btn-danger btn-sm" onClick={() => handleCancel(cls)}>Cancel</button>
                </div>
              </div>
              {reschedulingId === cls.id && (
                <div className="stack" style={{ borderTop: '1px solid var(--rule)', paddingTop: 10 }}>
                  <div>
                    <label>New start</label>
                    <input type="datetime-local" value={newStart} onChange={(e) => setNewStart(e.target.value)} />
                  </div>
                  <div>
                    <label>New end</label>
                    <input type="datetime-local" value={newEnd} onChange={(e) => setNewEnd(e.target.value)} />
                  </div>
                  <div className="hstack">
                    <button className="btn-sm" onClick={() => handleReschedule(cls)}>Confirm & notify batch</button>
                    <button className="btn-ghost btn-sm" onClick={() => setReschedulingId(null)}>Cancel edit</button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </Layout>
  );
}
