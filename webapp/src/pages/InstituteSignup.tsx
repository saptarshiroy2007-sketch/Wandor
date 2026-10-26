import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { instituteSignup, verifyInstituteSignup } from '../api/client';

// Replaces the old manual DB-insert + scripts/set_institute_password.py bootstrap -
// this creates the Institute row, but (like TeacherSignup) doesn't activate login
// until the OTP sent here is confirmed. See TeacherSignup.tsx for the `verify=1`
// skip-to-code-step behavior when InstituteLogin.tsx redirects here after a "phone
// not verified" 403.
export default function InstituteSignup() {
  const [searchParams] = useSearchParams();
  const skipToVerify = searchParams.get('verify') === '1';

  const [step, setStep] = useState<'form' | 'verify'>(skipToVerify ? 'verify' : 'form');
  const [name, setName] = useState('');
  const [ownerPhone, setOwnerPhone] = useState(searchParams.get('phone') || '');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [info, setInfo] = useState(skipToVerify ? "We've sent a new code to this phone." : '');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  async function handleSignup(e: React.FormEvent) {
    e.preventDefault();
    setError(''); setLoading(true);
    try {
      const res = await instituteSignup(name, ownerPhone, password);
      setInfo(res.message);
      setStep('verify');
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Could not sign up');
    } finally {
      setLoading(false);
    }
  }

  async function handleVerify(e: React.FormEvent) {
    e.preventDefault();
    setError(''); setLoading(true);
    try {
      await verifyInstituteSignup(ownerPhone, code);
      navigate('/institute');
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Incorrect or expired code');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page" style={{ maxWidth: 360, paddingTop: '15vh' }}>
      <div className="brand" style={{ justifyContent: 'center', marginBottom: 4 }}>
        <span className="brand-mark">W</span>
        <span className="brand-word" style={{ fontSize: 26 }}>Wandor</span>
      </div>
      <p>Institute sign up</p>

      {step === 'form' && (
        <form onSubmit={handleSignup} className="card stack">
          <input placeholder="Institute name" value={name} onChange={(e) => setName(e.target.value)} required />
          <input placeholder="Owner phone" value={ownerPhone} onChange={(e) => setOwnerPhone(e.target.value)} required />
          <input placeholder="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          {error && <p className="error">{error}</p>}
          <button type="submit" disabled={loading}>{loading ? 'Sending code…' : 'Sign up'}</button>
        </form>
      )}

      {step === 'verify' && (
        <form onSubmit={handleVerify} className="card stack">
          {info && <p style={{ margin: 0, fontSize: 13, color: 'var(--muted)' }}>{info}</p>}
          <div>
            <label>6-digit code sent to {ownerPhone}</label>
            <input
              placeholder="123456" value={code} maxLength={6}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} required
            />
          </div>
          {error && <p className="error">{error}</p>}
          <button type="submit" disabled={loading}>{loading ? 'Verifying…' : 'Verify & activate'}</button>
        </form>
      )}

      <p className="hstack" style={{ justifyContent: 'center', marginTop: 16 }}>
        <Link to="/institute-login">Already have an account? Log in</Link>
      </p>
      <p className="hstack" style={{ justifyContent: 'center', marginTop: 4 }}>
        <Link to="/">Back</Link>
      </p>
    </div>
  );
}
