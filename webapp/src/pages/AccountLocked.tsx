import { Link, useSearchParams } from 'react-router-dom';
import { canPayFlag, logout } from '../api/client';

// Shown when the API answers 403 + X-Account-Status. The Billing link appears only when the server
// said this user can pay (X-Account-Can-Pay, remembered by the client) and the lock is for payment.
export default function AccountLocked() {
  const [params] = useSearchParams();
  const suspended = params.get('why') === 'banned_admin';
  const canPay = !suspended && canPayFlag();

  const text = suspended
    ? 'This account has been suspended. Please contact Wandor support.'
    : canPay
      ? "Your plan wasn't renewed. Renew in Billing to restore access."
      : 'This account is inactive because the plan wasn\'t renewed. Please contact your institute.';

  function handleLogout() {
    logout();
    window.location.href = '/';
  }

  return (
    <div className="page" style={{ maxWidth: 420, paddingTop: '15vh' }}>
      <div className="brand" style={{ justifyContent: 'center', marginBottom: 4 }}>
        <span className="brand-mark">W</span>
        <span className="brand-word" style={{ fontSize: 26 }}>Wandor</span>
      </div>
      <div className="card stack">
        <h2 style={{ margin: 0 }}>Account locked</h2>
        <p>{text}</p>
        <div className="hstack">
          {canPay && <Link to="/billing">Go to Billing</Link>}
          <button className="btn-ghost" onClick={handleLogout}>Log out</button>
        </div>
      </div>
    </div>
  );
}
