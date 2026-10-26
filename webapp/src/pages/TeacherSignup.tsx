import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { teacherSignup, verifyTeacherSignup } from '../api/client';

// Independent teacher signup only - there's no institute field on this form on
// purpose. Joining an institute later happens when an institute admin adds you
// (see InstituteDashboard's "add teacher" flow), not something you self-attach to
// here. Students never get an equivalent page - only a teacher or institute admin
// can create a student login.
//
// Two steps now instead of one: signup sends an OTP instead of logging you straight
// in, and the account can't do anything until that code is confirmed. If `verify=1`
// is in the URL (Login.tsx redirects here when it gets a "phone not verified" 403,
// which itself sends a fresh code), skip straight to the code step - a signup form
// with the name/password fields blanked out would be a confusing thing to land on
// when you already have an account and just need to finish verifying it.
export default function TeacherSignup() {
  const [searchParams] = useSearchParams();
  const skipToVerify = searchParams.get('verify') === '1';

  const [step, setStep] = useState<'form' | 'verify'>(skipToVerify ? 'verify' : 'form');
  const [name, setName] = useState('');
  const [phone, setPhone] = useState(searchParams.get('phone') || '');
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
      const res = await teacherSignup(name, phone, password);
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
      await verifyTeacherSignup(phone, code);
      navigate('/');
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
      <p>Teacher sign up (independent)</p>

      {step === 'form' && (
        <form onSubmit={handleSignup} className="card stack">
          <input placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} required />
          <input placeholder="Phone" value={phone} onChange={(e) => setPhone(e.target.value)} required />
          <input placeholder="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          {error && <p className="error">{error}</p>}
          <button type="submit" disabled={loading}>{loading ? 'Sending code…' : 'Sign up'}</button>
        </form>
      )}

      {step === 'verify' && (
        <form onSubmit={handleVerify} className="card stack">
          {info && <p style={{ margin: 0, fontSize: 13, color: 'var(--muted)' }}>{info}</p>}
          <div>
            <label>6-digit code sent to {phone}</label>
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
        <Link to="/login">Already have an account? Log in</Link>
      </p>
      <p className="hstack" style={{ justifyContent: 'center', marginTop: 4 }}>
        <Link to="/">Back</Link>
      </p>
    </div>
  );
}
