import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { listClasses, cancelClass } from '../api/client';

interface ClassSession {
  id: string;
  batch: string;
  subject: string;
  start_time: string;
  status: string;
}

function statusPillClass(status: string) {
  switch (status) {
    case 'scheduled':
      return 'bg-teal-50 text-teal-700';
    case 'completed':
      return 'bg-amber-50 text-amber-700';
    case 'cancelled':
      return 'bg-red-50 text-red-600';
    default:
      return 'bg-black/5 text-ink/60';
  }
}

export default function Dashboard() {
  const [classes, setClasses] = useState<ClassSession[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listClasses()
      .then(setClasses)
      .finally(() => setLoading(false));
  }, []);

  async function handleCancel(id: string) {
    const reason = prompt('Reason for cancelling? (optional)') || undefined;
    await cancelClass(id, reason);
    setClasses(await listClasses());
  }

  return (
    <>
      {/* Heading row */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="font-display text-2xl font-semibold text-ink tracking-tight">
          Dashboard
        </h1>
        <Link
          to="/schedule"
          className="hidden md:inline-flex rounded-lg bg-teal-800 text-white text-sm font-medium px-4 py-2.5 hover:bg-teal-900 transition-colors"
        >
          + Schedule a class
        </Link>
      </div>

      {/* Loading state */}
      {loading && (
        <p className="text-sm text-ink/50 text-center py-12">Loading classes…</p>
      )}

      {/* Empty state */}
      {!loading && classes.length === 0 && (
        <div className="border-2 border-dashed border-black/10 rounded-xl px-6 py-12 text-center">
          <p className="text-sm text-ink/50">
            No classes scheduled yet.{' '}
            <Link to="/schedule" className="text-teal-700 hover:underline font-medium">
              Schedule your first class
            </Link>
          </p>
        </div>
      )}

      {/* Class cards */}
      {!loading && classes.length > 0 && (
        <ul className="space-y-3">
          {classes.map((c) => (
            <li
              key={c.id}
              className="bg-white rounded-xl border border-black/5 px-4 py-3.5 flex items-center justify-between gap-4"
            >
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-ink truncate">
                  {c.subject} — {c.batch}
                </p>
                <p className="text-xs text-ink/50 mt-0.5">
                  {new Date(c.start_time).toLocaleString(undefined, {
                    weekday: 'short',
                    day: 'numeric',
                    month: 'short',
                    hour: '2-digit',
                    minute: '2-digit',
                  })}
                </p>
              </div>
              <div className="flex items-center gap-3 shrink-0">
                <span
                  className={`text-xs font-medium px-2.5 py-1 rounded-full ${statusPillClass(c.status)}`}
                >
                  {c.status}
                </span>
                {c.status === 'scheduled' && (
                  <button
                    onClick={() => handleCancel(c.id)}
                    className="text-xs font-medium text-red-600 hover:underline"
                  >
                    Cancel
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

