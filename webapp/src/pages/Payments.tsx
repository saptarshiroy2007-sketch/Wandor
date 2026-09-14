import { useEffect, useState } from 'react';
import { listDueFees, sendFeeRemindersNow } from '../api/client';
import Layout from '../components/Layout';

interface FeeRecord {
  id: string;
  student_id: string;
  amount_due: number;
  amount_paid: number;
  is_paid: boolean;
  due_date: string;
}

export default function Payments() {
  const [fees, setFees] = useState<FeeRecord[]>([]);
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<{ checked: number; sent: number; failed: number } | null>(null);

  useEffect(() => {
    listDueFees().then(setFees);
  }, []);

  async function handleSendReminders() {
    setSending(true);
    setResult(null);
    try {
      const res = await sendFeeRemindersNow();
      setResult(res);
    } finally {
      setSending(false);
    }
  }

  return (
    <Layout>
      <div className="row">
        <h1>Fee tracker</h1>
        <button className="btn-sm" onClick={handleSendReminders} disabled={sending || fees.length === 0}>
          {sending ? 'Sending…' : 'Send reminders now'}
        </button>
      </div>
      {result && (
        <p className="empty" style={{ fontStyle: 'normal' }}>
          Checked {result.checked} unpaid fee{result.checked === 1 ? '' : 's'} — sent {result.sent}
          {result.failed > 0 ? `, ${result.failed} failed` : ''}.
        </p>
      )}
      {fees.length === 0 ? (
        <p className="empty">No fees due.</p>
      ) : (
        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          <table>
            <thead>
              <tr><th>Student</th><th>Due</th><th>Paid</th><th>Due date</th></tr>
            </thead>
            <tbody>
              {fees.map((f) => (
                <tr key={f.id}>
                  <td>{f.student_id}</td>
                  <td>₹{f.amount_due}</td>
                  <td>₹{f.amount_paid}</td>
                  <td>{new Date(f.due_date).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Layout>
  );
}
