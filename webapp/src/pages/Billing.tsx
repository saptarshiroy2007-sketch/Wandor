import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  listPlans, getBillingStatus, startSubscription, verifySubscription, cancelSubscription, changePlan,
  quoteUpgrade, startUpgrade, verifyUpgrade, listInvoices,
  Plan, BillingStatus, BillingCycle, UpgradeQuote, Invoice,
} from '../api/client';
import { openCheckout, CheckoutDismissed } from '../lib/razorpay';
import { inrPaise, fmtDate } from '../lib/money';
import Layout from '../components/Layout';

function statusLine(b: BillingStatus): string {
  switch (b.status) {
    case 'trialing':
      return b.scheduled_plan
        ? `Free trial of ${b.plan_label} — ends ${fmtDate(b.current_period_end)}. Your ${b.scheduled_plan} subscription starts then.`
        : `Free trial of ${b.plan_label} — ends ${fmtDate(b.current_period_end)}`;
    case 'active':
      return b.cancel_at_period_end
        ? `Cancelled — you keep ${b.plan_label} until ${fmtDate(b.current_period_end)}`
        : `Renews on ${fmtDate(b.current_period_end)}`;
    case 'cancelled': return `Cancelled — you keep ${b.plan_label} until ${fmtDate(b.current_period_end)}`;
    case 'past_due': return 'Your last payment failed. Razorpay will retry, and paid features continue for a few days. If it keeps failing, start a new subscription below with a working payment method.';
    case 'expired': return "Your subscription has ended — you're on the Free plan.";
    default: return "You're on the Free plan.";
  }
}

const limitText = (n: number | null, noun: string) => (n === null ? `Unlimited ${noun}` : `Up to ${n} ${noun}`);

export default function Billing() {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [billing, setBilling] = useState<BillingStatus | null>(null);
  const [cycle, setCycle] = useState<BillingCycle>('monthly');
  const [busy, setBusy] = useState<string | null>(null); // plan key being processed, or 'cancel'
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [quote, setQuote] = useState<UpgradeQuote | null>(null); // the upgrade-now panel
  const [invoices, setInvoices] = useState<Invoice[]>([]);

  function loadInvoices() {
    listInvoices().then(setInvoices).catch(() => setInvoices([])); // 403 for team members: just no list
  }

  function refresh() {
    getBillingStatus().then((b) => { setBilling(b); if (b.can_manage) loadInvoices(); })
      .catch(() => setError('Could not load your billing details.'));
  }

  useEffect(() => {
    listPlans().then(setPlans).catch(() => setError('Could not load plans.'));
    refresh();
  }, []);

  async function handleSubscribe(plan: Plan, cyc: BillingCycle = cycle) {
    setError(''); setNotice(''); setBusy(plan.key);
    try {
      const sub = await startSubscription(plan.key, cyc);
      const res = await openCheckout({
        key: sub.key_id,
        subscription_id: sub.subscription_id,
        name: 'Wandor',
        description: `${plan.label} plan (${cyc})`,
        prefill: { name: sub.name, contact: sub.contact },
      });
      try {
        const updated = await verifySubscription({
          razorpay_payment_id: res.razorpay_payment_id,
          razorpay_subscription_id: res.razorpay_subscription_id,
          razorpay_signature: res.razorpay_signature,
        });
        setBilling(updated);
        if (updated.plan === plan.key && updated.status === 'active') {
          setNotice(`You're on ${updated.plan_label}. Thank you!`);
        } else if (updated.status === 'trialing' && updated.scheduled_plan === plan.key) {
          setNotice(`You're subscribed. Your ${plan.label} plan starts when your trial ends on ${fmtDate(updated.current_period_end)} — nothing is charged before then.`);
        } else {
          // Checkout finished but Razorpay hasn't confirmed the charge yet (UPI can lag).
          // Say so instead of claiming an upgrade that hasn't happened; the webhook applies it.
          setNotice('Payment received — your plan will update within a minute.');
          setTimeout(refresh, 5000);
        }
      } catch {
        // Payment went through at Razorpay; only our instant confirmation failed. The
        // webhook will update the plan on its own - don't make it look like a failure.
        setNotice('Payment received. Your plan will update within a minute — refresh to check.');
        setTimeout(refresh, 5000);
      }
    } catch (err: any) {
      if (!(err instanceof CheckoutDismissed)) {
        setError(err?.response?.data?.detail || err?.message || 'Could not start the subscription.');
      }
    } finally {
      setBusy(null);
    }
  }

  async function handleQuote(plan: Plan) {
    setError(''); setNotice(''); setBusy(plan.key);
    try {
      setQuote(await quoteUpgrade(plan.key));
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Could not price the upgrade.');
    } finally {
      setBusy(null);
    }
  }

  async function handleUpgrade() {
    if (!quote) return;
    setError(''); setNotice(''); setBusy('upgrade');
    try {
      const o = await startUpgrade(quote.to_plan);
      const res = await openCheckout({
        key: o.key_id,
        order_id: o.order_id,
        amount: o.total_paise,
        currency: 'INR',
        name: 'Wandor',
        description: `Upgrade to ${o.to_plan_label} (${o.cycle}), rest of this period`,
        prefill: { name: o.name, contact: o.contact },
      });
      setQuote(null);
      try {
        const updated = await verifyUpgrade({
          razorpay_order_id: res.razorpay_order_id,
          razorpay_payment_id: res.razorpay_payment_id,
          razorpay_signature: res.razorpay_signature,
        });
        setBilling(updated);
        loadInvoices();
        setNotice(`You're now on ${updated.plan_label}. Thank you!`);
      } catch (err: any) {
        const detail: string = err?.response?.data?.detail || '';
        if (err?.response?.status === 409 && /refund/i.test(detail)) {
          setError(detail); // money was taken but the upgrade could not be applied
        } else {
          // Payment went through at Razorpay; the webhook applies the upgrade on its own.
          setNotice('Payment received. Your plan will upgrade within a minute — refresh to check.');
          setTimeout(refresh, 5000);
        }
      }
    } catch (err: any) {
      if (!(err instanceof CheckoutDismissed)) {
        setError(err?.response?.data?.detail || err?.message || 'Could not start the upgrade.');
      }
    } finally {
      setBusy(null);
    }
  }

  async function handleChange(plan: Plan) {
    setError(''); setNotice(''); setBusy(plan.key);
    try {
      const updated = await changePlan(plan.key, cycle);
      setBilling(updated);
      setNotice(`Switching to ${plan.label} (${cycle}) at your next renewal on ${fmtDate(updated.current_period_end)}.`);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Could not change your plan.');
    } finally {
      setBusy(null);
    }
  }

  async function handleCancel() {
    if (!window.confirm('Cancel your subscription? You keep your paid plan until the end of the current period.')) return;
    setError(''); setNotice(''); setBusy('cancel');
    try {
      setBilling(await cancelSubscription());
      setNotice('Your subscription will not renew.');
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Could not cancel.');
    } finally {
      setBusy(null);
    }
  }

  if (!billing) {
    return <Layout><h1>Plan &amp; billing</h1>{error ? <p className="error">{error}</p> : <p className="empty">Loading…</p>}</Layout>;
  }

  const canChange = billing.status === 'active' && !billing.cancel_at_period_end;
  const trialSubscribed = billing.status === 'trialing' && !!billing.scheduled_plan; // paid plan queued behind the trial
  const canCancel = billing.can_manage && (canChange || billing.status === 'past_due' || trialSubscribed);

  return (
    <Layout>
      <h1>Plan &amp; billing</h1>

      <div className="card stack">
        <div className="row">
          <div>
            <span className="badge">{billing.plan_label}</span>{' '}
            {billing.billing_cycle && <span className="badge badge-muted">{billing.billing_cycle}</span>}
          </div>
          {canCancel && (
            <button className="btn-ghost btn-sm" onClick={handleCancel} disabled={busy !== null}>
              {busy === 'cancel' ? 'Cancelling…' : 'Cancel subscription'}
            </button>
          )}
        </div>
        <p style={{ margin: 0 }}>{statusLine(billing)}</p>
        {billing.scheduled_plan && billing.status !== 'trialing' && (
          <p style={{ margin: 0, color: 'var(--muted)' }}>
            Switching to {billing.scheduled_plan} ({billing.scheduled_cycle}) at your next renewal.
          </p>
        )}
        <p style={{ margin: 0, color: 'var(--muted)' }}>
          Students: {billing.students_used}{billing.students_limit !== null ? ` of ${billing.students_limit}` : ''}
          {billing.owner_kind === 'institute' && (
            <> · Teachers: {billing.teachers_used}{billing.teachers_limit !== null ? ` of ${billing.teachers_limit}` : ''}</>
          )}
          {' · '}Online fee collection: {billing.online_fee_collection ? 'on' : 'off'}
          {' · '}Fee reminders & notices: {billing.fee_reminders ? 'on' : 'off'}
        </p>
      </div>

      {!billing.can_manage && (
        <p className="empty" style={{ fontStyle: 'normal' }}>
          Your institute's admin manages the plan. You can see what's included here.
        </p>
      )}
      {billing.can_manage && billing.upgrade_renewal === 'reauthorise' && (() => {
        const cur = plans.find((x) => x.key === billing.plan);
        const cyc = (billing.billing_cycle || 'monthly') as BillingCycle;
        return (
          <div className="card stack">
            <strong style={{ color: 'var(--ink)' }}>One more step to keep your plan</strong>
            <p style={{ margin: 0 }}>
              Your upgrade is paid and active. Your current subscription ends on {fmtDate(billing.current_period_end)},
              so subscribe again to carry on after that — you won't be charged twice.
            </p>
            {cur && (
              <div>
                <button className="btn-sm" onClick={() => handleSubscribe(cur, cyc)} disabled={busy !== null}>
                  {busy === cur.key ? 'Opening…' : `Subscribe again (${cur.label}, ${cyc})`}
                </button>
              </div>
            )}
          </div>
        );
      })()}
      {billing.can_manage && billing.upgrade_renewal === 'failed' && (
        <p className="error">
          Your upgrade is active, but we couldn't switch your next renewal to the new price. It may renew at the
          old price — we've been alerted and will sort it out.
        </p>
      )}
      {quote && (
        <div className="card stack">
          <strong style={{ color: 'var(--ink)' }}>Upgrade to {quote.to_plan_label} now</strong>
          <p style={{ margin: 0 }}>
            For the {Math.ceil(quote.remaining_days)} day{Math.ceil(quote.remaining_days) === 1 ? '' : 's'} left in this
            period (until {fmtDate(quote.period_end)}). After that, {quote.to_plan_label} renews at its normal {quote.cycle} price.
          </p>
          <div>
            <div className="row"><span style={{ color: 'var(--muted)' }}>{quote.to_plan_label}, rest of period</span><span>{inrPaise(quote.charge_base_paise)}</span></div>
            <div className="row"><span style={{ color: 'var(--muted)' }}>Unused {quote.from_plan_label}, credited</span><span>− {inrPaise(quote.credit_base_paise)}</span></div>
            <div className="row"><span style={{ color: 'var(--muted)' }}>Subtotal (excl. GST)</span><span>{inrPaise(quote.base_paise)}</span></div>
            <div className="row"><span style={{ color: 'var(--muted)' }}>GST ({quote.gst_rate_percent}%)</span><span>{inrPaise(quote.gst_paise)}</span></div>
            <div className="row"><strong style={{ color: 'var(--ink)' }}>Pay now</strong><strong style={{ color: 'var(--ink)' }}>{inrPaise(quote.total_paise)}</strong></div>
          </div>
          <div className="hstack">
            <button className="btn-sm" onClick={handleUpgrade} disabled={busy !== null}>
              {busy === 'upgrade' ? 'Opening…' : `Pay ${inrPaise(quote.total_paise)}`}
            </button>
            <button className="btn-ghost btn-sm" onClick={() => setQuote(null)} disabled={busy !== null}>Not now</button>
          </div>
        </div>
      )}
      {notice && <p style={{ color: 'var(--ink)' }}>{notice}</p>}
      {error && <p className="error">{error}</p>}

      <div className="row">
        <h2 style={{ margin: 0 }}>Plans</h2>
        <div className="hstack">
          <button className={cycle === 'monthly' ? 'btn-secondary btn-sm' : 'btn-ghost btn-sm'} onClick={() => setCycle('monthly')}>Monthly</button>
          <button className={cycle === 'yearly' ? 'btn-secondary btn-sm' : 'btn-ghost btn-sm'} onClick={() => setCycle('yearly')}>Yearly</button>
        </div>
      </div>

      {plans.map((p) => {
        const isCurrent = p.key === billing.plan;
        const isCurrentExact = isCurrent && (p.key === 'free' || billing.billing_cycle === cycle);
        const price = cycle === 'monthly' ? p.price_monthly : p.price_yearly;
        const available = p.key === 'free' || (cycle === 'monthly' ? p.monthly_available : p.yearly_available);
        const saving = cycle === 'yearly' && p.price_monthly > 0 ? p.price_monthly * 12 - p.price_yearly : 0;
        const totalPaise = cycle === 'monthly' ? p.total_monthly_paise : p.total_yearly_paise;
        const curPlan = plans.find((x) => x.key === billing.plan);
        // "Upgrade now" is only for a higher plan on the SAME cycle, with nothing already scheduled
        const canUpgradeNow = canChange && !billing.scheduled_plan && !!curPlan && p.price_monthly > curPlan.price_monthly
          && billing.billing_cycle === cycle;

        let action: React.ReactNode = null;
        if (p.key !== 'free' && billing.can_manage) {
          if (isCurrentExact && billing.status !== 'trialing' && billing.status !== 'past_due') {
            action = <span className="badge badge-muted">Current plan</span>;
          } else if (!available) {
            action = <span className="badge badge-muted">Not available yet</span>;
          } else if (trialSubscribed) {
            action = p.key === billing.scheduled_plan && cycle === billing.scheduled_cycle
              ? <span className="badge badge-muted">Starts after trial</span>
              : <span className="badge badge-muted">Cancel to change</span>;
          } else if (canChange) {
            action = (
              <div className="hstack">
                {canUpgradeNow && (
                  <button className="btn-sm" onClick={() => handleQuote(p)} disabled={busy !== null}>
                    {busy === p.key ? 'Pricing…' : 'Upgrade now'}
                  </button>
                )}
                <button className="btn-secondary btn-sm" onClick={() => handleChange(p)} disabled={busy !== null}>
                  {busy === p.key && !canUpgradeNow ? 'Working…' : 'Switch at next renewal'}
                </button>
              </div>
            );
          } else {
            action = (
              <button className="btn-sm" onClick={() => handleSubscribe(p)} disabled={busy !== null}>
                {busy === p.key ? 'Opening…'
                  : billing.status === 'trialing' ? 'Subscribe (starts after trial)'
                  : billing.status === 'past_due' ? 'Start new subscription'
                  : 'Subscribe'}
              </button>
            );
          }
        } else if (isCurrent) {
          action = <span className="badge badge-muted">Current plan</span>;
        }

        return (
          <div className="card row" key={p.key} style={isCurrent ? { borderColor: 'var(--signal-red)' } : undefined}>
            <div className="stack" style={{ gap: 4 }}>
              <div style={{ color: 'var(--ink)', fontWeight: 600 }}>
                {p.label}{' '}
                <span style={{ color: 'var(--muted)', fontWeight: 400 }}>
                  {price === 0 ? 'Free' : `₹${price.toLocaleString('en-IN')} + GST / ${cycle === 'monthly' ? 'month' : 'year'}`}
                </span>
                {price > 0 && p.gst_rate_percent > 0 && totalPaise > 0 && (
                  <span style={{ color: 'var(--muted)', fontWeight: 400 }}> ({inrPaise(totalPaise)} with {p.gst_rate_percent}% GST)</span>
                )}
                {saving > 0 && <span className="badge badge-muted" style={{ marginLeft: 8 }}>Save ₹{saving.toLocaleString('en-IN')}</span>}
              </div>
              <p style={{ margin: 0 }}>
                {limitText(p.max_students, 'students')} · {limitText(p.max_teachers, 'teachers')} ·{' '}
                {p.online_fee_collection ? 'Students can pay fees online' : 'Record fees manually'} ·{' '}
                {p.fee_reminders ? 'WhatsApp fee reminders & receipts' : 'No fee reminders or receipts'}
              </p>
            </div>
            {action}
          </div>
        );
      })}

      {billing.can_manage && (
        <>
          <h2 style={{ marginBottom: 0 }}>Invoices</h2>
          {invoices.length === 0 ? (
            <p className="empty">No invoices yet. One appears here after each successful charge.</p>
          ) : (
            invoices.map((i) => (
              <div className="card row" key={i.id}>
                <div className="stack" style={{ gap: 4 }}>
                  <div style={{ color: 'var(--ink)', fontWeight: 600 }}>
                    {i.invoice_number}{' '}
                    <span style={{ color: 'var(--muted)', fontWeight: 400 }}>{fmtDate(i.issued_at)}</span>
                    {i.kind === 'proration' && <span className="badge badge-muted" style={{ marginLeft: 8 }}>Upgrade</span>}
                  </div>
                  <p style={{ margin: 0 }}>
                    {i.description || `${i.plan_label} plan${i.billing_cycle ? ` (${i.billing_cycle})` : ''}`} · {inrPaise(i.total_paise)} incl. GST
                  </p>
                </div>
                <Link to={`/billing/invoice/${i.id}`}><button className="btn-secondary btn-sm">View / print</button></Link>
              </div>
            ))
          )}
        </>
      )}
    </Layout>
  );
}
