import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getBillingStatus, getRole, BillingStatus } from '../api/client';

// Grace-period warning for teachers and institute admins. Renders nothing while the account is active.
export default function AccessBanner() {
  const role = getRole();
  const [status, setStatus] = useState<BillingStatus | null>(null);

  useEffect(() => {
    if (role !== 'teacher' && role !== 'institute_admin') return;
    getBillingStatus().then(setStatus).catch(() => {});
  }, [role]);

  if (!status || status.access_state !== 'grace') return null;
  const until = status.ban_at ? new Date(status.ban_at).toLocaleDateString() : null;
  return (
    <div className="card hstack" role="alert" style={{ borderColor: 'var(--signal-red)', marginBottom: 12 }}>
      <span>
        Your plan has lapsed. Attendance, tests and analytics are paused until you renew.
        {until && ` Access ends on ${until}.`}
      </span>
      <Link to="/billing">Billing</Link>
    </div>
  );
}
