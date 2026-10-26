import { useState } from 'react';
import { Link } from 'react-router-dom';
import { MyFee } from '../api/client';
import { openCheckout, CheckoutDismissed } from '../lib/razorpay';

interface Props {
  fees: MyFee[];
  onlineAvailable: boolean;
  /** Creates the Razorpay order for a fee (student or parent endpoint). `amount` is only
   *  sent for a part-payment; omitted = pay everything still owed. */
  createOrder: (feeId: string, amount?: number) => Promise<{ key_id: string; order_id: string; amount_paise: number }>;
  /** Server-side signature check + instant "paid" (student or parent endpoint). */
  verify: (p: { razorpay_order_id: string; razorpay_payment_id: string; razorpay_signature: string }) => Promise<unknown>;
  /** Re-fetch the fee list. */
  reload: () => void;
  /** Shown in Checkout next to the fee description, e.g. the child's name for a parent. */
  descriptionPrefix?: string;
}

const inr = (n: number) => `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;

/** Fee list with a Pay button per unpaid fee - shared by the student and parent
 *  dashboards so both run the identical Checkout flow. Fees the teacher allowed to be
 *  paid in instalments get an amount box; every payment links to its receipt. */
export default function PayableFees({ fees, onlineAvailable, createOrder, verify, reload, descriptionPrefix }: Props) {
  const [payingId, setPayingId] = useState<string | null>(null);
  const [amounts, setAmounts] = useState<Record<string, string>>({});
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  async function handlePay(fee: MyFee) {
    setError(''); setNotice('');
    const left = Math.round((fee.amount_due - fee.amount_paid) * 100) / 100;
    const typed = (amounts[fee.id] ?? '').trim();
    let amount: number | undefined;
    if (fee.allow_partial && typed !== '') {
      amount = Number(typed);
      if (!Number.isFinite(amount) || amount <= 0) { setError('Enter an amount greater than zero.'); return; }
      if (amount > left) { setError(`That is more than the ${inr(left)} still owed.`); return; }
      if (amount === left) amount = undefined; // same as paying it all
    }
    setPayingId(fee.id);
    try {
      const order = await createOrder(fee.id, amount);
      const label = fee.description || 'Fee payment';
      const res = await openCheckout({
        key: order.key_id,
        order_id: order.order_id,
        amount: order.amount_paise,
        currency: 'INR',
        name: 'Wandor',
        description: descriptionPrefix ? `${descriptionPrefix} - ${label}` : label,
      });
      try {
        await verify({
          razorpay_order_id: res.razorpay_order_id,
          razorpay_payment_id: res.razorpay_payment_id,
          razorpay_signature: res.razorpay_signature,
        });
        setNotice('Payment successful. Thank you!');
      } catch {
        // The payment itself went through; only our instant confirmation failed. The
        // server also hears about it from Razorpay, so it will show as paid shortly.
        setNotice('Payment received. It will show as paid in a moment.');
        setTimeout(reload, 4000);
      }
      setAmounts((a) => ({ ...a, [fee.id]: '' }));
      reload();
    } catch (err: any) {
      if (!(err instanceof CheckoutDismissed)) {
        setError(err?.response?.data?.detail || err?.message || 'Could not start the payment.');
      }
    } finally {
      setPayingId(null);
    }
  }

  return (
    <>
      {notice && <p style={{ color: 'var(--ink)' }}>{notice}</p>}
      {error && <p className="error">{error}</p>}
      {fees.map((f) => {
        const overdue = !f.is_paid && new Date(f.due_date) < new Date();
        const left = Math.round((f.amount_due - f.amount_paid) * 100) / 100;
        const partlyPaid = !f.is_paid && f.amount_paid > 0;
        return (
          <div className="card" key={f.id}>
            <div className="row">
              <div>
                <div style={{ color: 'var(--ink)' }}>
                  {inr(f.amount_due)}{f.description ? ` · ${f.description}` : ''}
                </div>
                <p style={{ margin: '2px 0 0' }}>
                  {f.is_paid
                    ? `Paid${f.paid_at ? ` on ${new Date(f.paid_at).toLocaleDateString()}` : ''}`
                    : `Due ${new Date(f.due_date).toLocaleDateString()}`}
                  {partlyPaid && ` · ${inr(f.amount_paid)} paid, ${inr(left)} left`}
                </p>
              </div>
              {f.is_paid ? (
                <span className="badge">Paid</span>
              ) : onlineAvailable ? (
                <div className="hstack">
                  {f.allow_partial && (
                    <input
                      type="number" min="1" step="0.01" style={{ width: 110 }}
                      placeholder={`Amount (max ${left})`}
                      value={amounts[f.id] ?? ''}
                      onChange={(e) => setAmounts((a) => ({ ...a, [f.id]: e.target.value }))}
                      disabled={payingId !== null}
                    />
                  )}
                  <button className="btn-sm" onClick={() => handlePay(f)} disabled={payingId !== null}>
                    {payingId === f.id ? 'Opening…' : overdue ? 'Pay now (overdue)' : 'Pay now'}
                  </button>
                </div>
              ) : (
                <span className="badge badge-muted">Pay the teacher directly</span>
              )}
            </div>
            {f.payments.length > 0 && (
              <div style={{ marginTop: 8 }}>
                {f.payments.map((p) => (
                  <p key={p.id} style={{ margin: '2px 0', fontSize: '0.9em' }}>
                    {inr(p.amount)} {p.mode === 'manual' ? 'paid to teacher' : 'paid online'}
                    {p.paid_at ? ` · ${new Date(p.paid_at).toLocaleDateString()}` : ''}
                    {p.refunded_amount > 0 && ` · ${inr(p.refunded_amount)} refunded`}
                    {' · '}<Link to={`/receipt/${p.id}`}>Receipt {p.receipt_no}</Link>
                  </p>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </>
  );
}
