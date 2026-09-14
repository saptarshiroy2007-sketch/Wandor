import { useEffect, useState } from 'react';
import { scheduleClass, listClasses, cancelClass, rescheduleClass } from '../api/client';
import Layout from '../components/Layout';

interface ClassSession {
  id: string;
  batch: string;
  subject: string;
  start_time: string;
  end_time: string;
  status: 'scheduled' | 'cancelled' | 'completed';
}

export default function ScheduleClass() {
  const [batch, setBatch] = useState('');
  const [subject, setSubject] = useState('');
  const [startTime, setStartTime] = useState('');
  const [endTime, setEndTime] = useState('');
  const [saving, setSaving] = useState(false);

  const [classes, setClasses] = useState<ClassSession[]>([]);
  const [reschedulingId, setReschedulingId] = useState<string | null>(null);
  const [newStart, setNewStart] = useState('');
  const [newEnd, setNewEnd] = useState('');

  function refresh() {
    listClasses().then(setClasses);
  }

  useEffect(() => {
    refresh();
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await scheduleClass({
        batch, subject,
        start_time: new Date(startTime).toISOString(),
        end_time: new Date(endTime).toISOString(),
      });
      setBatch(''); setSubject(''); setStartTime(''); setEndTime('');
      refresh();
    } finally {
      setSaving(false);
    }
  }

  async function handleCancel(cls: ClassSession) {
    const reason = window.prompt(`Cancel ${cls.subject} for ${cls.batch}? Reason (optional):`);
    if (reason === null) return; // they hit cancel on the prompt itself
    await cancelClass(cls.id, reason || undefined);
    refresh();
  }

  function openReschedule(cls: ClassSession) {
    setReschedulingId(cls.id);
    setNewStart(cls.start_time.slice(0, 16));
    setNewEnd(cls.end_time.slice(0, 16));
  }

  async function handleReschedule(cls: ClassSession) {
    await rescheduleClass(cls.id, {
      start_time: new Date(newStart).toISOString(),
      end_time: new Date(newEnd).toISOString(),
    });
    setReschedulingId(null);
    refresh();
  }

  const upcoming = classes.filter((c) => c.status === 'scheduled');

  return (
    <Layout>
      <h1>Schedule a class</h1>
      <form onSubmit={handleSubmit} className="card stack">
        <div>
          <label>Batch</label>
          <input placeholder="e.g. Class 10 - Batch A" value={batch} onChange={(e) => setBatch(e.target.value)} />
        </div>
        <div>
          <label>Subject</label>
          <input placeholder="Subject" value={subject} onChange={(e) => setSubject(e.target.value)} />
        </div>
        <div>
          <label>Start</label>
          <input type="datetime-local" value={startTime} onChange={(e) => setStartTime(e.target.value)} />
        </div>
        <div>
          <label>End</label>
          <input type="datetime-local" value={endTime} onChange={(e) => setEndTime(e.target.value)} />
        </div>
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
                  <strong>{cls.subject}</strong> — {cls.batch}
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
