import { useEffect, useState } from 'react';
import {
  AdminAccount, AdminMoney, AdminStats, AdminStatusFilter,
  getAdminStats, listAdminAccounts, extendGrace, banAccount, liftBan, logout,
} from '../api/client';
import ThemeToggle from '../components/ThemeToggle';

const FILTERS: AdminStatusFilter[] = ['all', 'active', 'grace', 'banned', 'trial'];

const inr = (paise: number) =>
  '₹' + (paise / 100).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : '-');
const errText = (err: any) => {
  const d = err?.response?.data?.detail;
  return typeof d === 'string' ? d : Array.isArray(d) ? d.map((x: any) => x.msg).join('; ') : 'Something went wrong';
};

function Tile({ label, value, sub, foot }: { label: string; value: string; sub?: string; foot?: string }) {
  return (
    <div className="card stack" style={{ flex: '1 1 160px', minWidth: 160 }}>
      <span style={{ fontSize: 12, color: 'var(--muted)' }}>{label}</span>
      <strong style={{ fontSize: 24 }}>{value}</strong>
      {sub && <span style={{ fontSize: 12, color: 'var(--muted)' }}>{sub}</span>}
      {foot && <span style={{ fontSize: 11, color: 'var(--muted)' }}>{foot}</span>}
    </div>
  );
}

const moneyTile = (label: string, m: AdminMoney) =>
  <Tile label={label} value={inr(m.base_paise)} sub={`+ ${inr(m.gst_paise)} GST`} />;

export default function AdminDashboard() {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [accounts, setAccounts] = useState<AdminAccount[]>([]);
  const [filter, setFilter] = useState<AdminStatusFilter>('all');
  const [error, setError] = useState('');
  const [graceFor, setGraceFor] = useState<string | null>(null);
  const [graceUntil, setGraceUntil] = useState('');
  const [graceNote, setGraceNote] = useState('');

  function refresh() {
    setError('');
    getAdminStats().then(setStats).catch((e) => setError(errText(e)));
    listAdminAccounts(filter).then(setAccounts).catch((e) => setError(errText(e)));
  }
  useEffect(refresh, [filter]);

  async function run(action: () => Promise<unknown>) {
    setError('');
    try {
      await action();
      setGraceFor(null);
      refresh();
    } catch (e) {
      setError(errText(e));
    }
  }

  function handleBan(a: AdminAccount) {
    const reason = window.prompt(`Reason for banning ${a.name}?`);
    if (reason && reason.trim()) run(() => banAccount(a.subscription_id, reason.trim()));
  }

  function handleExtend(e: React.FormEvent, a: AdminAccount) {
    e.preventDefault();
    if (!graceUntil) return setError('Pick a date and time');
    run(() => extendGrace(a.subscription_id, new Date(graceUntil).toISOString(), graceNote.trim() || undefined));
  }

  const manual = (a: AdminAccount) => a.admin_banned;
  const canExtend = (a: AdminAccount) =>
    !manual(a) && (a.access_state === 'grace' || (a.access_state === 'banned' && a.access_reason === 'payment'));

  return (
    <div className="page">
      <div className="hstack" style={{ justifyContent: 'space-between' }}>
        <h1>Platform admin</h1>
        <div className="hstack">
          <ThemeToggle />
          <button className="btn-ghost btn-sm" onClick={() => { logout(); window.location.href = '/admin-login'; }}>Log out</button>
        </div>
      </div>

      {stats && (
        <div className="hstack" style={{ alignItems: 'stretch', marginBottom: 16 }}>
          <Tile label="Paying accounts" value={String(stats.paying_accounts)} />
          <Tile label="Total users" value={String(stats.total_users)} />
          <Tile label="Users gained this week" value={String(stats.users_gained_week)} foot="Parents are not counted." />
          {moneyTile('Revenue, all time', stats.revenue.total)}
          {moneyTile('Revenue, this week', stats.revenue.week)}
          {moneyTile('Revenue, this month', stats.revenue.month)}
        </div>
      )}

      <div className="hstack" style={{ marginBottom: 8 }}>
        <label htmlFor="status-filter">Status</label>
        <select id="status-filter" value={filter} onChange={(e) => setFilter(e.target.value as AdminStatusFilter)}>
          {FILTERS.map((f) => <option key={f} value={f}>{f}</option>)}
        </select>
      </div>
      {error && <p className="error">{error}</p>}

      <div style={{ overflowX: 'auto' }}>
        <table>
          <thead>
            <tr>
              <th>Name</th><th>Kind</th><th>Plan</th><th>Status</th><th>Period end</th><th>Ban date</th><th>Paying</th><th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {accounts.length === 0 && <tr><td colSpan={8} className="empty">No accounts.</td></tr>}
            {accounts.map((a) => (
              <tr key={a.subscription_id}>
                <td>{a.name}<br /><span style={{ fontSize: 12, color: 'var(--muted)' }}>{a.phone}</span></td>
                <td>{a.kind}</td>
                <td>{a.plan}</td>
                <td>
                  <span className={`badge ${a.access_state === 'banned' ? 'badge-danger' : a.access_state === 'grace' ? 'badge-flag' : ''}`}>
                    {a.access_state}
                  </span>
                  {a.access_reason === 'admin' && <span className="badge badge-muted" title={a.admin_ban_reason ?? ''} style={{ marginLeft: 4 }}>manual</span>}
                </td>
                <td>{when(a.current_period_end)}</td>
                <td>{when(a.ban_at)}</td>
                <td>{a.is_paying ? <span className="badge">paying</span> : '-'}</td>
                <td>
                  <div className="hstack">
                    {canExtend(a) && graceFor !== a.subscription_id && (
                      <button className="btn-ghost btn-sm" onClick={() => { setGraceFor(a.subscription_id); setGraceUntil(''); setGraceNote(''); }}>Extend grace</button>
                    )}
                    {!manual(a) && <button className="btn-ghost btn-sm" onClick={() => handleBan(a)}>Ban</button>}
                    {manual(a) && <button className="btn-ghost btn-sm" onClick={() => run(() => liftBan(a.subscription_id))}>Lift ban</button>}
                  </div>
                  {graceFor === a.subscription_id && (
                    <form className="stack" style={{ marginTop: 6 }} onSubmit={(e) => handleExtend(e, a)}>
                      <input type="datetime-local" aria-label="Grace until" value={graceUntil} onChange={(e) => setGraceUntil(e.target.value)} />
                      <input placeholder="Note (optional)" maxLength={300} value={graceNote} onChange={(e) => setGraceNote(e.target.value)} />
                      <div className="hstack">
                        <button type="submit" className="btn-sm">Save</button>
                        <button type="button" className="btn-ghost btn-sm" onClick={() => setGraceFor(null)}>Cancel</button>
                      </div>
                    </form>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
