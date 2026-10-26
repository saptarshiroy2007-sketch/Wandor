import { useEffect, useState } from 'react';
import {
  myChild, myChildAttendance, myChildTests,
  getChildFeesPayable, createParentPaymentOrder, verifyParentFeePayment, MyFee,
} from '../api/client';
import PayableFees from '../components/PayableFees';
import Layout from '../components/Layout';

interface Child {
  id: string;
  name: string;
  batch_name: string | null;
}

interface AttendanceSummary {
  total_classes: number;
  present_count: number;
  attendance_pct: number;
}

interface TestAttempt {
  id: string;
  test_title: string;
  submitted_at: string | null;
  score: number | null;
  max_score: number | null;
  graded_at: string | null;
  is_flagged: boolean;
}

export default function ParentDashboard() {
  const [child, setChild] = useState<Child | null>(null);
  const [attendance, setAttendance] = useState<AttendanceSummary | null>(null);
  const [fees, setFees] = useState<MyFee[]>([]);
  const [onlineAvailable, setOnlineAvailable] = useState(false);
  const [tests, setTests] = useState<TestAttempt[]>([]);

  function loadFees() {
    getChildFeesPayable()
      .then((r) => { setFees(r.fees); setOnlineAvailable(r.online_payment_available); })
      .catch(() => {});
  }

  useEffect(() => {
    myChild().then(setChild);
    myChildAttendance().then(setAttendance);
    loadFees();
    myChildTests().then(setTests);
  }, []);

  return (
    <Layout>
      <h1>{child ? `${child.name}'s dashboard` : 'Dashboard'}</h1>
      {child?.batch_name && <p>Batch: {child.batch_name}</p>}

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
        <PayableFees
          fees={fees}
          onlineAvailable={onlineAvailable}
          createOrder={createParentPaymentOrder}
          verify={verifyParentFeePayment}
          reload={loadFees}
          descriptionPrefix={child?.name}
        />
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
                    {t.score != null
                      ? `${t.score}${t.max_score != null ? `/${t.max_score}` : ''}`
                      : t.submitted_at
                        ? 'Awaiting grading'
                        : '—'}
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
