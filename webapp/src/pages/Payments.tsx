import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  listFeeRecords, createFees, markFeePaid, deleteFee, getPayoutStatus, listBatches, listStudents,
  sendFeeRemindersNow, FeeRecordDetail, PayoutStatus, BatchOut,
} from '../api/client';
import Layout from '../components/Layout';

interface StudentLite { id: string; name: string; }
type Filter = 'unpaid' | 'paid' | 'all';

const inr = (n: number) => `₹${n.toLocaleString('en-IN')}`;
const fmtDate = (iso: string) => new Date(iso).toLocaleDateString();

export default function Payments() {
  const [fees, setFees] = useState<FeeRecordDetail[]>([]);
  const [filter, setFilter] = useState<Filter>('unpaid');
  const [payout, setPayout] = useState<PayoutStatus | null>(null);

  const [batches, setBatches] = useState<BatchOut[]>([]);
  const [students, setStudents] = useState<StudentLite[]>([]);
  const [target, setTarget] = useState<'batch' | 'student'>('batch');
  const [batchId, setBatchId] = useState('');
  const [studentId, setStudentId] = useState('');
  const [amount, setAmount] = useState('');
  const [dueDate, setDueDate] = useState('');
  const [description, setDescription] = useState('');
  const [allowPartial, setAllowPartial] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [reminderError, setReminderError] = useState('');
  const [notice, setNotice] = useState('');

  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<{ checked: number; sent: number; failed: number; skipped_plan: number } | null>(null);

  function refresh() {
    listFeeRecords().then(setFees);
  }

  useEffect(() => {
    refresh();
    getPayoutStatus().then(setPayout).catch(() => {});
    listBatches().then(setBatches);
    listStudents().then(setStudents);
  }, []);

  const shown = useMemo(
    () => fees.filter((f) => (filter === 'all' ? true : filter === 'paid' ? f.is_paid : !f.is_paid)),
    [fees, filter],
  );
  const unpaidCount = fees.filter((f) => !f.is_paid).length;

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setError(''); setNotice('');
    const amt = Number(amount);
    if (!amt || amt <= 0) { setError('Enter an amount greater than zero.'); return; }
    if (!dueDate) { setError('Pick a due date.'); return; }
    if (target === 'batch' ? !batchId : !studentId) { setError(target === 'batch' ? 'Pick a batch.' : 'Pick a student.'); return; }
    setSaving(true);
    try {
      const res = await createFees({
        ...(target === 'batch' ? { batch_id: batchId } : { student_ids: [studentId] }),
        amount: amt,
        due_date: `${dueDate}T00:00:00`,
        description: description.trim() || undefined,
        allow_partial: allowPartial,
      });
      setNotice(`Added ${res.created_count} fee${res.created_count === 1 ? '' : 's'}.`);
      setAmount(''); setDescription('');
      refresh();
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Could not add fees.');
    } finally {
      setSaving(false);
    }
  }

  // Records money received outside the app. The box is pre-filled with the whole balance;
  // type less to record a part-payment.
  async function handleMarkPaid(f: FeeRecordDetail) {
    const left = Math.round((f.amount_due - f.amount_paid) * 100) / 100;
    const raw = window.prompt(`Amount received in cash/UPI (₹${left} is still owed):`, String(left));
    if (raw === null) return;
    const amt = Number(raw);
    if (!Number.isFinite(amt) || amt <= 0) { setError('Enter an amount greater than zero.'); return; }
    setError('');
    try { await markFeePaid(f.id, amt === left ? undefined : amt); refresh(); }
    catch (err: any) { setError(err?.response?.data?.detail || 'Could not update that fee.'); }
  }

  async function handleDelete(id: string) {
    if (!window.confirm('Delete this unpaid fee?')) return;
    setError('');
    try { await deleteFee(id); refresh(); }
    catch (err: any) { setError(err?.response?.data?.detail || 'Could not delete that fee.'); }
  }

  async function handleSendReminders() {
    setSending(true);
    setResult(null);
    setReminderError('');
    try {
      setResult(await sendFeeRemindersNow());
    } catch (err: any) {
      // 402 = plan doesn't include reminders, 429 = too many attempts; both carry a plain-string detail
      const detail = err?.response?.data?.detail;
      setReminderError(typeof detail === 'string' ? detail : 'Could not send reminders.');
    } finally {
      setSending(false);
    }
  }

  return (
    <Layout>
      <div className="row">
        <h1>Fee tracker</h1>
        <button className="btn-sm" onClick={handleSendReminders} disabled={sending || unpaidCount === 0}>
          {sending ? 'Sending…' : 'Send reminders now'}
        </button>
      </div>
      {result && (
        <p className="empty" style={{ fontStyle: 'normal' }}>
          Checked {result.checked} unpaid fee{result.checked === 1 ? '' : 's'} — sent {result.sent}
          {result.failed > 0 ? `, ${result.failed} failed` : ''}
          {result.skipped_plan > 0 ? `, ${result.skipped_plan} skipped (plan has no reminders)` : ''}.
        </p>
      )}
      {reminderError && (
        <p className="error">{reminderError} {reminderError.includes('plan') && <Link to="/billing">See plans</Link>}</p>
      )}

      {payout && !payout.ready && (
        <div className="card">
          <p style={{ margin: 0, color: 'var(--ink)' }}>Students can't pay online yet.</p>
          <p style={{ margin: '4px 0 0' }}>
            {!payout.online_fee_collection_allowed
              ? <>Your current plan doesn't include online fee collection. <Link to="/billing">See plans</Link>.</>
              : "Your payout account isn't linked yet — ask Wandor to set it up. Until then you can record cash or UPI payments with “Mark paid”."}
          </p>
        </div>
      )}

      <h2>Add fees</h2>
      <form onSubmit={handleCreate} className="card stack">
        <div className="hstack">
          <select value={target} onChange={(e) => setTarget(e.target.value as 'batch' | 'student')}>
            <option value="batch">Whole batch</option>
            <option value="student">One student</option>
          </select>
          {target === 'batch' ? (
            <select value={batchId} onChange={(e) => setBatchId(e.target.value)} style={{ flex: 1 }}>
              <option value="">Select batch…</option>
              {batches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </select>
          ) : (
            <select value={studentId} onChange={(e) => setStudentId(e.target.value)} style={{ flex: 1 }}>
              <option value="">Select student…</option>
              {students.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          )}
        </div>
        <div className="hstack">
          <input type="number" min="1" step="0.01" placeholder="Amount (₹)" value={amount} onChange={(e) => setAmount(e.target.value)} />
          <input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
          <input placeholder="Description (e.g. March tuition)" value={description} maxLength={200}
                 onChange={(e) => setDescription(e.target.value)} style={{ flex: 1 }} />
        </div>
        <label className="hstack" style={{ gap: 6 }}>
          <input type="checkbox" checked={allowPartial} onChange={(e) => setAllowPartial(e.target.checked)} />
          <span>Let them pay in instalments online</span>
        </label>
        {error && <p className="error">{error}</p>}
        {notice && <p style={{ margin: 0, color: 'var(--ink)' }}>{notice}</p>}
        <div><button type="submit" disabled={saving}>{saving ? 'Adding…' : 'Add fees'}</button></div>
      </form>

      <div className="row">
        <h2 style={{ margin: 0 }}>Fees</h2>
        <div className="hstack">
          {(['unpaid', 'paid', 'all'] as Filter[]).map((f) => (
            <button key={f} className={filter === f ? 'btn-secondary btn-sm' : 'btn-ghost btn-sm'} onClick={() => setFilter(f)}>
              {f[0].toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {shown.length === 0 ? (
        <p className="empty">{filter === 'unpaid' ? 'No unpaid fees.' : 'Nothing here yet.'}</p>
      ) : (
        <div className="card" style={{ padding: 0, overflow: 'auto' }}>
          <table>
            <thead>
              <tr><th>Student</th><th>For</th><th>Amount</th><th>Paid</th><th>Due</th><th>Status</th><th></th></tr>
            </thead>
            <tbody>
              {shown.map((f) => {
                const overdue = !f.is_paid && new Date(f.due_date) < new Date();
                return (
                  <tr key={f.id}>
                    <td>{f.student_name}{f.batch_name ? <span style={{ color: 'var(--muted)' }}> · {f.batch_name}</span> : null}</td>
                    <td>{f.description || '—'}</td>
                    <td>{inr(f.amount_due)}</td>
                    <td>{f.amount_paid > 0 ? inr(f.amount_paid) : '—'}</td>
                    <td>{fmtDate(f.due_date)}</td>
                    <td>
                      {f.is_paid
                        ? <>
                            <span className="badge">{f.payment_mode === 'online' ? 'Paid online' : 'Paid'}</span>
                          </>
                        : f.amount_paid > 0
                          ? <span className="badge badge-muted">Part-paid · {inr(f.amount_due - f.amount_paid)} left</span>
                          : overdue ? <span className="badge badge-danger">Overdue</span> : <span className="badge badge-muted">Due</span>}
                      {f.duplicate_payment && (
                        <span className="badge badge-flag" style={{ marginLeft: 6 }} title="More money was taken for this fee than is owed. Refund the extra payment from your Razorpay dashboard; this flag clears by itself once the refund completes.">
                          Overpaid — refund needed
                        </span>
                      )}
                      {f.payments.map((p) => (
                        <div key={p.id} style={{ fontSize: '0.85em', color: 'var(--muted)' }}>
                          {inr(p.amount)} {p.mode === 'manual' ? 'recorded' : 'online'}{p.paid_by && p.paid_by !== 'teacher' ? ` by ${p.paid_by}` : ''}
                          {p.refunded_amount > 0 ? ` · ${inr(p.refunded_amount)} refunded` : ''}
                          {' · '}<Link to={`/receipt/${p.id}`}>{p.receipt_no}</Link>
                        </div>
                      ))}
                    </td>
                    <td style={{ whiteSpace: 'nowrap' }}>
                      {!f.is_paid && (
                        <>
                          <button className="btn-ghost btn-sm" onClick={() => handleMarkPaid(f)}>{f.amount_paid > 0 ? 'Record payment' : 'Mark paid'}</button>{' '}
                          {f.amount_paid <= 0 && <button className="btn-ghost btn-sm" onClick={() => handleDelete(f.id)}>Delete</button>}
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Layout>
  );
}
