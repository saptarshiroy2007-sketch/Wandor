import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import Layout from '../components/Layout';
import { getRole, isDarkTheme, setTheme, getMyProfile, changePassword, joinInstitute, MyProfile as MyProfileData } from '../api/client';

export default function Settings() {
  const role = getRole();

  // ── Appearance ───────────────────────────────────────────────────────────
  const [dark, setDark] = useState(isDarkTheme());

  function handleThemeToggle() {
    const next = !dark;
    setDark(next);
    setTheme(next);
  }

  // ── Profile ───────────────────────────────────────────────────────────────
  const [profile, setProfile] = useState<MyProfileData | null>(null);
  const [profileErr, setProfileErr] = useState('');

  useEffect(() => {
    if (role !== 'teacher') return;
    getMyProfile()
      .then(setProfile)
      .catch(() => setProfileErr('Could not load profile.'));
  }, [role]);

  // ── Join institute (independent teachers only) ──────────────────────────────
  const [instPhone, setInstPhone] = useState('');
  const [instPassword, setInstPassword] = useState('');
  const [joinError, setJoinError] = useState('');
  const [joinLoading, setJoinLoading] = useState(false);

  async function handleJoinInstitute(e: React.FormEvent) {
    e.preventDefault();
    setJoinError(''); setJoinLoading(true);
    try {
      const updated = await joinInstitute(instPhone, instPassword);
      setProfile((p) => (p ? { ...p, institute_id: updated.institute_id } : p));
      setInstPhone(''); setInstPassword('');
    } catch (err: any) {
      setJoinError(err?.response?.data?.detail || 'Could not join that institute. Check the phone number and password.');
    } finally {
      setJoinLoading(false);
    }
  }

  // ── Change password ───────────────────────────────────────────────────────
  const [oldPw, setOldPw] = useState('');
  const [newPw, setNewPw] = useState('');
  const [confirmPw, setConfirmPw] = useState('');
  const [pwError, setPwError] = useState('');
  const [pwOk, setPwOk] = useState(false);
  const [pwLoading, setPwLoading] = useState(false);

  async function handleChangePassword(e: React.FormEvent) {
    e.preventDefault();
    setPwError('');
    setPwOk(false);
    if (newPw.length < 8) { setPwError('New password must be at least 8 characters.'); return; }
    if (newPw !== confirmPw) { setPwError('New passwords do not match.'); return; }
    setPwLoading(true);
    try {
      await changePassword(oldPw, newPw);
      setPwOk(true);
      setOldPw(''); setNewPw(''); setConfirmPw('');
    } catch (err: any) {
      setPwError(err?.response?.data?.detail || 'Could not change password. Check your current password.');
    } finally {
      setPwLoading(false);
    }
  }

  return (
    <Layout>
      <h1>Settings</h1>

      {/* 1. Appearance */}
      <h2>Appearance</h2>
      <div className="card">
        <div className="row">
          <span style={{ fontSize: 14, color: 'var(--ink)' }}>Dark mode</span>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', width: 'auto' }}>
            <input
              type="checkbox"
              checked={dark}
              onChange={handleThemeToggle}
              style={{
                width: 36, height: 20, appearance: 'none', WebkitAppearance: 'none',
                background: dark ? 'var(--signal-red)' : 'var(--paper-line)',
                borderRadius: 10, position: 'relative', cursor: 'pointer',
                border: 'none', outline: 'none', transition: 'background 0.2s', flexShrink: 0,
              }}
            />
            <span style={{ fontSize: 12, color: 'var(--muted)', fontFamily: 'var(--font-mono)' }}>
              {dark ? 'ON' : 'OFF'}
            </span>
          </label>
        </div>
        <p style={{ marginTop: 8, fontSize: 12, marginBottom: 0 }}>Preference is saved across sessions.</p>
      </div>

      {/* 2. Profile */}
      <h2>Profile</h2>
      <div className="card">
        {(role === 'teacher' || role === 'student' || role === 'institute_admin') && (
          <div className="row">
            <span style={{ fontSize: 13, color: 'var(--muted)' }}>
              Name, photo, bio{role === 'teacher' ? ', education' : ''} and contact email
            </span>
            <Link to="/my-profile"><button type="button" className="btn-sm">Edit My Profile</button></Link>
          </div>
        )}
        {role === 'parent' && <p className="empty">Your details are linked to your child&apos;s student record.</p>}
      </div>

      {/* 2a. Plan & billing — teachers (independent: their own plan; institute member: read-only) and institute admins */}
      {(role === 'teacher' || role === 'institute_admin') && (
        <>
          <h2>Plan &amp; billing</h2>
          <div className="card row">
            <span style={{ fontSize: 13, color: 'var(--muted)' }}>
              Your plan, usage and subscription
            </span>
            <Link to="/billing"><button type="button" className="btn-sm">Manage plan</button></Link>
          </div>
        </>
      )}

      {/* 2b. Join institute — independent teachers only */}
      {role === 'teacher' && profile && !profile.institute_id && (
        <>
          <h2>Join an institute</h2>
          <div className="card">
            <p style={{ marginTop: 0, fontSize: 13, color: 'var(--muted)' }}>
              Your account is currently independent. If a coaching institute wants you on their
              team, enter their login phone number and password below to join — ask their admin
              for these, the same credentials they use to log into the Institute dashboard.
            </p>
            <form className="stack" onSubmit={handleJoinInstitute}>
              <div>
                <label>Institute's phone number</label>
                <input value={instPhone} onChange={(e) => setInstPhone(e.target.value)} required />
              </div>
              <div>
                <label>Institute's password</label>
                <input type="password" value={instPassword} onChange={(e) => setInstPassword(e.target.value)} required />
              </div>
              {joinError && <p className="error">{joinError}</p>}
              <button type="submit" disabled={joinLoading} style={{ alignSelf: 'flex-start' }}>
                {joinLoading ? 'Joining…' : 'Join institute'}
              </button>
            </form>
          </div>
        </>
      )}
      {role === 'teacher' && profile && profile.institute_id && (
        <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: -8 }}>
          You're part of an institute. Batch access is managed by your institute's admin.
        </p>
      )}

      {/* 3. Change password — hidden for parent */}
      {role !== 'parent' && (
        <>
          <h2>Change password</h2>
          <div className="card">
            {pwOk && (
              <p style={{ color: 'var(--ink-blue)', fontFamily: 'var(--font-mono)', fontSize: 13, marginBottom: 12 }}>
                ✓ Password changed successfully.
              </p>
            )}
            <form className="stack" onSubmit={handleChangePassword}>
              <div>
                <label>Current password</label>
                <input type="password" value={oldPw} onChange={(e) => setOldPw(e.target.value)} required autoComplete="current-password" />
              </div>
              <div>
                <label>New password</label>
                <input type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} required minLength={8} autoComplete="new-password" />
              </div>
              <div>
                <label>Confirm new password</label>
                <input type="password" value={confirmPw} onChange={(e) => setConfirmPw(e.target.value)} required autoComplete="new-password" />
              </div>
              {pwError && <p className="error">{pwError}</p>}
              <button type="submit" disabled={pwLoading} style={{ alignSelf: 'flex-start' }}>
                {pwLoading ? 'Saving…' : 'Change password'}
              </button>
            </form>
          </div>
        </>
      )}
    </Layout>
  );
}
