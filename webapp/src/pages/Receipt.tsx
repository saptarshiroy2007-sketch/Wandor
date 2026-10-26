import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { getReceipt, Receipt as ReceiptData } from '../api/client';

const inr = (n: number) => `₹${n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/** Printable receipt for one payment. Works for a teacher, student or parent - the API
 *  only returns it if it belongs to them. Deliberately outside the app Layout so
 *  "Print / save as PDF" produces just the receipt. */
export default function Receipt() {
  const { paymentId } = useParams();
  const nav = useNavigate();
  const [r, setR] = useState<ReceiptData | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!paymentId) return;
    getReceipt(paymentId).then(setR).catch(() => setError('Receipt not found.'));
  }, [paymentId]);

  const row = (label: string, value: React.ReactNode) => (
    <div className="row" style={{ padding: '6px 0' }}>
      <span style={{ color: 'var(--muted)' }}>{label}</span><span style={{ color: 'var(--ink)' }}>{value}</span>
    </div>
  );

  return (
    <div style={{ maxWidth: 520, margin: '32px auto', padding: '0 16px' }}>
      <div className="no-print" style={{ marginBottom: 12 }}>
        <button className="btn-ghost btn-sm" onClick={() => nav(-1)}>← Back</button>{' '}
        {r && <button className="btn-sm" onClick={() => window.print()}>Print / save as PDF</button>}
      </div>
      {error && <p className="error">{error}</p>}
      {!r && !error && <p className="empty">Loading…</p>}
      {r && (
        <div className="card">
          <h1 style={{ marginTop: 0 }}>Payment receipt</h1>
          {row('Receipt no.', r.receipt_no)}
          {row('Received by', r.issued_by || '—')}
          {row('Student', r.issued_to)}
          {row('For', r.fee_description || 'Fee payment')}
          {row('Date', r.paid_at ? new Date(r.paid_at).toLocaleString() : '—')}
          {row('Method', r.mode === 'online' ? 'Online (Razorpay)' : 'Recorded by teacher (cash / UPI / other)')}
          {r.razorpay_payment_id && row('Payment ID', r.razorpay_payment_id)}
          <hr />
          {row('Amount paid', <strong>{inr(r.amount)}</strong>)}
          {r.refunded_amount > 0 && row('Refunded', inr(r.refunded_amount))}
          {row('Fee total', inr(r.fee_total))}
          {row('Balance still due on this fee', inr(r.fee_balance))}
          {r.status !== 'paid' && (
            <p className="error" style={{ marginBottom: 0 }}>
              {r.status === 'refunded' ? 'This payment has been fully refunded.' : 'This payment has been partly refunded.'}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
