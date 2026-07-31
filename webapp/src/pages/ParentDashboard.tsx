import { useEffect, useState } from 'react';
import { myChild, myChildAttendance, myChildFees, myChildTests } from '../api/client';
import Layout from '../components/Layout';

interface Child {
  id: string;
  name: string;
  batch: string | null;
}

interface AttendanceSummary {
  total_classes: number;
  present_count: number;
  attendance_pct: number;
}

interface FeeRecord {
  id: string;
  amount_due: number;
  amount_paid: number;
  is_paid: boolean;
  due_date: string;
}

interface TestAttempt {
  id: string;
  test_title: string;
  submitted_at: string | null;
  score: number | null;
  is_flagged: boolean;
}

export default function ParentDashboard() {
  const [child, setChild] = useState<Child | null>(null);
  const [attendance, setAttendance] = useState<AttendanceSummary | null>(null);
  const [fees, setFees] = useState<FeeRecord[]>([]);
  const [tests, setTests] = useState<TestAttempt[]>([]);

  useEffect(() => {
    myChild().then(setChild);
    myChildAttendance().then(setAttendance);
    myChildFees().then(setFees);
    myChildTests().then(setTests);
  }, []);

  return (
    <Layout>
      <h1>{child ? `${child.name}'s dashboard` : 'Dashboard'}</h1>
      {child?.batch && <p>Batch: {child.batch}</p>}

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

      <h2>Fees</h2>
      {fees.length === 0 ? (
        <p className="empty">No fee records yet.</p>
      ) : (
        <div className="card" style={{ padding: 0 }}>
          <table>
            <thead>
              <tr><th>Due date</th><th>Amount due</th><th>Amount paid</th><th>Status</th></tr>
            </thead>
            <tbody>
              {fees.map((f) => (
                <tr key={f.id}>
                  <td>{new Date(f.due_date).toLocaleDateString()}</td>
                  <td>₹{f.amount_due}</td>
                  <td>₹{f.amount_paid}</td>
                  <td><span className={`badge ${f.is_paid ? '' : 'badge-danger'}`}>{f.is_paid ? 'Paid' : 'Due'}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2>Test scores</h2>
      {tests.length === 0 ? (
        <p className="empty">No completed tests yet.</p>
      ) : (
        <div className="card" style={{ padding: 0 }}>
          <table>
            <thead>
              <tr><th>Test</th><th>Submitted</th><th>Score</th></tr>
            </thead>
            <tbody>
              {tests.map((t) => (
                <tr key={t.id}>
                  <td>{t.test_title}</td>
                  <td>{t.submitted_at ? new Date(t.submitted_at).toLocaleDateString() : '—'}</td>
                  <td>
                    {t.score ?? '—'}
                    {t.is_flagged && <span className="badge badge-danger" style={{ marginLeft: 6 }}>flagged</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Layout>
  );
}
