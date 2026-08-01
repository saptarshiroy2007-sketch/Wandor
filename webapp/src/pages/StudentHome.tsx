import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { myAttendanceSummary, listAvailableTests } from '../api/client';
import Layout from '../components/Layout';

interface AttendanceSummary { total_classes: number; present_count: number; attendance_pct: number; }
interface TestOut { id: string; title: string; test_type: string; duration_minutes: number; topic?: string | null; }

export default function StudentHome() {
  const [attendance, setAttendance] = useState<AttendanceSummary | null>(null);
  const [tests, setTests] = useState<TestOut[]>([]);

  useEffect(() => {
    myAttendanceSummary().then(setAttendance);
    listAvailableTests().then(setTests);
  }, []);

  return (
    <Layout>
      <h1>My dashboard</h1>

      <h2>Attendance</h2>
      <div className="card">
        {attendance ? (
          <p style={{ margin: 0, color: 'var(--ink)' }}>
            {attendance.attendance_pct}% <span style={{ color: 'var(--muted)' }}>({attendance.present_count} of {attendance.total_classes} classes)</span>
          </p>
        ) : (
          <p className="empty">Loading…</p>
        )}
      </div>

      <h2>Tests</h2>
      {tests.length === 0 ? (
        <p className="empty">No tests available yet.</p>
      ) : (
        tests.map((t) => (
          <Link to={`/test/${t.id}`} key={t.id} className="card row" style={{ display: 'flex', color: 'inherit' }}>
            <div>
              <div style={{ color: 'var(--ink)' }}>{t.title}</div>
              <p style={{ margin: '2px 0 0' }}>{t.duration_minutes} min</p>
            </div>
            <span className="badge">{t.test_type === 'mcq_auto' ? 'MCQ' : 'Document'}</span>
          </Link>
        ))
      )}
    </Layout>
  );
}
