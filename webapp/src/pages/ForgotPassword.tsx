import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { requestPasswordReset, confirmPasswordReset, ResetRole } from '../api/client';

const ROLE_LABEL: Record<ResetRole, string> = {
  teacher: 'Teacher',
  student: 'Student',
  institute_admin: 'Institute owner',
};

const ROLE_HOME: Record<ResetRole, string> = {
  teacher: '/',
  student: '/home',
  institute_admin: '/institute',
};

const ROLE_LOGIN_PATH: Record<ResetRole, string> = {
  teacher: '/login',
  student: '/student-login',
  institute_admin: '/institute-login',
};

export default function ForgotPassword() {
  const [searchParams] = useSearchParams();
  const initialRole = (searchParams.get('role') as ResetRole) || 'teacher';
  const [role, setRole] = useState<ResetRole>(initialRole);

  const [step, setStep] = useState<'phone' | 'code'>('phone');
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [info, setInfo] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  async function handleRequest(e: React.FormEvent) {
    e.preventDefault();
    setError(''); setLoading(true);
    try {
      const res = await requestPasswordReset(role, phone);
      setInfo(res.message);
      setStep('code');
    } catch {
      setError('Something went wrong sending the code. Try again in a moment.');
    } finally {
      setLoading(false);
    }
  }

  async function handleConfirm(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    if (newPassword !== confirmPassword) {
      setError("Passwords don't match");
      return;
    }
    if (newPassword.length < 8) {
      setError('Password must be at least 8 characters');
      return;
    }
    setLoading(true);
    try {
      await confirmPasswordReset(role, phone, code, newPassword);
      navigate(ROLE_HOME[role]);
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
      <p>Reset password</p>

      {step === 'phone' && (
        <form onSubmit={handleRequest} className="card stack">
          <div>
            <label>I am a</label>
            <select value={role} onChange={(e) => setRole(e.target.value as ResetRole)}>
              <option value="teacher">Teacher</option>
              <option value="student">Student</option>
              <option value="institute_admin">Institute owner</option>
            </select>
          </div>
          <input
            placeholder="Phone number" value={phone}
            onChange={(e) => setPhone(e.target.value)} required
          />
          {error && <p className="error">{error}</p>}
          <button type="submit" disabled={loading}>
            {loading ? 'Sending…' : 'Send code'}
          </button>
        </form>
      )}

      {step === 'code' && (
        <form onSubmit={handleConfirm} className="card stack">
          <p style={{ margin: 0, fontSize: 13, color: 'var(--muted)' }}>{info}</p>
          <div>
            <label>6-digit code</label>
            <input
              placeholder="123456" value={code} maxLength={6}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} required
            />
          </div>
          <div>
            <label>New password</label>
            <input
              type="password" placeholder="At least 8 characters" value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)} required
            />
          </div>
          <div>
            <label>Confirm new password</label>
            <input
              type="password" value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)} required
            />
          </div>
          {error && <p className="error">{error}</p>}
          <button type="submit" disabled={loading}>
            {loading ? 'Resetting…' : 'Reset password'}
          </button>
          <button
            type="button" className="btn-ghost"
            onClick={() => { setStep('phone'); setCode(''); setError(''); }}
          >
            Use a different phone number
          </button>
        </form>
      )}

      <p className="hstack" style={{ justifyContent: 'center', marginTop: 16 }}>
        <Link to={ROLE_LOGIN_PATH[role]}>Back to {ROLE_LABEL[role]} login</Link>
      </p>
    </div>
  );
}
