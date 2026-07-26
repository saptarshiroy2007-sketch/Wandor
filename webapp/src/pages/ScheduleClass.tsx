import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { scheduleClass } from '../api/client';

export default function ScheduleClass() {
  const [batch, setBatch] = useState('');
  const [subject, setSubject] = useState('');
  const [startTime, setStartTime] = useState('');
  const [endTime, setEndTime] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await scheduleClass({
        batch,
        subject,
        start_time: new Date(startTime).toISOString(),
        end_time: new Date(endTime).toISOString(),
      });
      navigate('/');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <h1 className="font-display text-2xl font-semibold text-ink tracking-tight mb-2">
        Schedule a class
      </h1>
      <p className="text-sm text-ink/50 mb-6">
        The batch will be auto-notified once you schedule it.
      </p>

      <div className="bg-white rounded-xl border border-black/5 px-4 py-3.5">
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="batch" className="sr-only">
              Batch
            </label>
            <input
              id="batch"
              placeholder="Batch (e.g. Class 10 — Batch A)"
              value={batch}
              onChange={(e) => setBatch(e.target.value)}
              required
              className="w-full rounded-lg border border-black/10 px-3.5 py-2.5 text-sm text-ink placeholder:text-ink/40 focus:outline-none focus:ring-2 focus:ring-teal-600/30 focus:border-teal-600"
            />
          </div>
          <div>
            <label htmlFor="subject" className="sr-only">
              Subject
            </label>
            <input
              id="subject"
              placeholder="Subject"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              required
              className="w-full rounded-lg border border-black/10 px-3.5 py-2.5 text-sm text-ink placeholder:text-ink/40 focus:outline-none focus:ring-2 focus:ring-teal-600/30 focus:border-teal-600"
            />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label
                htmlFor="startTime"
                className="block text-xs font-medium text-ink/60 mb-1"
              >
                Start time
              </label>
              <input
                id="startTime"
                type="datetime-local"
                value={startTime}
                onChange={(e) => setStartTime(e.target.value)}
                required
                className="w-full rounded-lg border border-black/10 px-3.5 py-2.5 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-teal-600/30 focus:border-teal-600"
              />
            </div>
            <div>
              <label
                htmlFor="endTime"
                className="block text-xs font-medium text-ink/60 mb-1"
              >
                End time
              </label>
              <input
                id="endTime"
                type="datetime-local"
                value={endTime}
                onChange={(e) => setEndTime(e.target.value)}
                required
                className="w-full rounded-lg border border-black/10 px-3.5 py-2.5 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-teal-600/30 focus:border-teal-600"
              />
            </div>
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-lg bg-teal-800 text-white text-sm font-medium py-2.5 hover:bg-teal-900 disabled:opacity-60 transition-colors"
          >
            {submitting ? 'Scheduling…' : 'Schedule & notify batch'}
          </button>
        </form>
      </div>
    </>
  );
}

