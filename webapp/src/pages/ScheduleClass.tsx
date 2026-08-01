import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { scheduleClass } from '../api/client';
import Layout from '../components/Layout';

export default function ScheduleClass() {
  const [batch, setBatch] = useState('');
  const [subject, setSubject] = useState('');
  const [startTime, setStartTime] = useState('');
  const [endTime, setEndTime] = useState('');
  const [saving, setSaving] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await scheduleClass({
        batch, subject,
        start_time: new Date(startTime).toISOString(),
        end_time: new Date(endTime).toISOString(),
      });
      navigate('/');
    } finally {
      setSaving(false);
    }
  }

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
    </Layout>
  );
}
