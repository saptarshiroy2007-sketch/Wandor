import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { scheduleClass } from '../api/client';

export default function ScheduleClass() {
  const [batch, setBatch] = useState('');
  const [subject, setSubject] = useState('');
  const [startTime, setStartTime] = useState('');
  const [endTime, setEndTime] = useState('');
  const navigate = useNavigate();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    await scheduleClass({
      batch, subject,
      start_time: new Date(startTime).toISOString(),
      end_time: new Date(endTime).toISOString(),
    });
    navigate('/');
  }

  return (
    <form onSubmit={handleSubmit}>
      <h1>Schedule a class</h1>
      <input placeholder="Batch (e.g. Class 10 - Batch A)" value={batch} onChange={(e) => setBatch(e.target.value)} />
      <input placeholder="Subject" value={subject} onChange={(e) => setSubject(e.target.value)} />
      <label>Start<input type="datetime-local" value={startTime} onChange={(e) => setStartTime(e.target.value)} /></label>
      <label>End<input type="datetime-local" value={endTime} onChange={(e) => setEndTime(e.target.value)} /></label>
      <button type="submit">Schedule & notify batch</button>
    </form>
  );
}
