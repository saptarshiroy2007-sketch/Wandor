import { useEffect, useState } from 'react';
import Layout from '../components/Layout';
import { getRole, isDarkTheme, setTheme, getMyProfile, changePassword } from '../api/client';

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
  const [profile, setProfile] = useState<{ name: string; phone: string } | null>(null);
  const [profileErr, setProfileErr] = useState('');

  useEffect(() => {
    if (role !== 'teacher') return;
    getMyProfile()
      .then(setProfile)
      .catch(() => setProfileErr('Could not load profile.'));
  }, [role]);

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
        {role === 'teacher' && (
          <>
            {profileErr && <p className="error">{profileErr}</p>}
            {profile ? (
              <div className="stack" style={{ gap: 12 }}>
                <div>
                  <label>Name</label>
                  <div style={{ fontSize: 15, color: 'var(--ink)', paddingTop: 2 }}>{profile.name}</div>
                </div>
                <div>
                  <label>Phone</label>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 14, color: 'var(--ink)', paddingTop: 2 }}>{profile.phone}</div>
                </div>
              </div>
            ) : !profileErr ? (
              <p className="empty">Loading…</p>
            ) : null}
          </>
        )}
        {role === 'student' && <p className="empty">Profile editing for students coming soon.</p>}
        {role === 'institute_admin' && (
          <p className="empty">Institute profile is managed from the <a href="/institute">Institute dashboard</a>.</p>
        )}
        {role === 'parent' && <p className="empty">Your details are linked to your child&apos;s student record.</p>}
      </div>

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
