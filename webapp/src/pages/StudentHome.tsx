import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { myAttendanceSummary, listAvailableTests, getMyFees, createPaymentOrder, verifyFeePayment, listMyClasses, listMyAttempts, ClassOut, AttemptOut, MyFee } from '../api/client';
import PayableFees from '../components/PayableFees';
import Layout from '../components/Layout';

interface AttendanceSummary { total_classes: number; present_count: number; attendance_pct: number; }
interface TestOut { id: string; title: string; test_type: string; duration_minutes: number; topic?: string | null; }

export default function StudentHome() {
  const [attendance, setAttendance] = useState<AttendanceSummary | null>(null);
  const [tests, setTests] = useState<TestOut[]>([]);
  const [classes, setClasses] = useState<ClassOut[]>([]);
  const [attempts, setAttempts] = useState<AttemptOut[]>([]);

  const [fees, setFees] = useState<MyFee[]>([]);
  const [onlineAvailable, setOnlineAvailable] = useState(false);
  function loadFees() {
    getMyFees().then((r) => { setFees(r.fees); setOnlineAvailable(r.online_payment_available); }).catch(() => {});
  }

  useEffect(() => {
    myAttendanceSummary().then(setAttendance);
    listAvailableTests().then(setTests);
    listMyClasses().then(setClasses).catch(() => {});
    listMyAttempts().then(setAttempts).catch(() => {});
    loadFees();
  }, []);

  const now = Date.now();
  const upcoming = classes
    .filter((c) => c.status === 'cancelled' ? +new Date(c.end_time) > now - 7 * 864e5 : +new Date(c.end_time) > now)
    .sort((a, b) => +new Date(a.start_time) - +new Date(b.start_time));
  const fmt = (iso: string) => new Date(iso).toLocaleString([], { weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' });

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

      <h2>Classes</h2>
      {upcoming.length === 0 ? (
        <p className="empty">No upcoming classes.</p>
      ) : (
        upcoming.map((c) => (
          <div className="card row" key={c.id} style={{ opacity: c.status === 'cancelled' ? 0.7 : 1 }}>
            <div>
              <div style={{ color: 'var(--ink)', textDecoration: c.status === 'cancelled' ? 'line-through' : 'none' }}>{c.subject}</div>
              <p style={{ margin: '2px 0 0' }}>{fmt(c.start_time)}</p>
            </div>
            <span className={`badge ${c.status === 'cancelled' ? 'badge-danger' : ''}`}>{c.status === 'cancelled' ? 'Cancelled' : 'Scheduled'}</span>
          </div>
        ))
      )}

      {fees.length > 0 && (
        <>
          <h2>Fees</h2>
          <PayableFees
            fees={fees}
            onlineAvailable={onlineAvailable}
            createOrder={createPaymentOrder}
            verify={verifyFeePayment}
            reload={loadFees}
          />
        </>
      )}

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

      {attempts.length > 0 && (
        <>
          <h2>My results</h2>
          {attempts.filter((a) => a.submitted_at).map((a) => (
            <div className="card row" key={a.id}>
              <div>
                <div style={{ color: 'var(--ink)' }}>{a.test_title}</div>
                <p style={{ margin: '2px 0 0' }}>{fmt(a.submitted_at!)}</p>
              </div>
              <span className="badge">{a.score === null ? 'Awaiting grading' : `${a.score}/${a.max_score}`}</span>
            </div>
          ))}
        </>
      )}
    </Layout>
  );
}
