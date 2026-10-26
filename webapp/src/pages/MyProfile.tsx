import { useEffect, useRef, useState } from 'react';
import Layout from '../components/Layout';
import {
  getRole, getMyProfile, updateMyProfile,
  getMyStudentProfile, updateMyStudentProfile,
  getMyInstituteProfile, updateMyInstituteProfile,
  uploadProfilePhoto, MyProfile as MyProfileData,
} from '../api/client';

// One screen, three backends - teacher/student/institute_admin each have their own
// get/update pair (see client.ts), picked at the top based on the logged-in role.
// A parent never lands here at all (Settings.tsx doesn't link this page for them -
// a parent's own info IS their child's student record, nothing separate to edit).
export default function MyProfile() {
  const role = getRole();

  const [profile, setProfile] = useState<MyProfileData | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');

  const [name, setName] = useState('');
  const [bio, setBio] = useState('');
  const [education, setEducation] = useState('');
  const [email, setEmail] = useState('');

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [saved, setSaved] = useState(false);

  const [photoUploading, setPhotoUploading] = useState(false);
  const [photoError, setPhotoError] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  function load() {
    const fetcher = role === 'student' ? getMyStudentProfile
      : role === 'institute_admin' ? getMyInstituteProfile
      : getMyProfile;
    fetcher()
      .then((p) => {
        setProfile(p);
        setName(p.name);
        setBio(p.bio || '');
        setEducation(p.education || '');
        setEmail(p.email || '');
      })
      .catch(() => setLoadError('Could not load your profile.'))
      .finally(() => setLoading(false));
  }

  useEffect(load, [role]);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaveError('');
    setSaved(false);
    setSaving(true);
    try {
      let updated: MyProfileData;
      if (role === 'student') {
        updated = await updateMyStudentProfile({ name, bio, email });
      } else if (role === 'institute_admin') {
        updated = await updateMyInstituteProfile({ name, bio, email });
      } else {
        updated = await updateMyProfile({ name, bio, education, email });
      }
      setProfile(updated);
      setSaved(true);
    } catch (err: any) {
      setSaveError(err?.response?.data?.detail || 'Could not save changes');
    } finally {
      setSaving(false);
    }
  }

  async function handlePhotoPick(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file || !role || role === 'parent' || role === 'platform_admin') return;
    setPhotoError('');
    setPhotoUploading(true);
    try {
      const url = await uploadProfilePhoto(role, file);
      setProfile((p) => (p ? { ...p, photo_url: url } : p));
      load(); // completion % changes once a photo is set - refresh rather than guess it client-side
    } catch (err: any) {
      setPhotoError(err?.response?.data?.detail || 'Could not upload photo');
    } finally {
      setPhotoUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }

  if (loading) {
    return (
      <Layout>
        <h1>My Profile</h1>
        <p className="empty">Loading…</p>
      </Layout>
    );
  }

  if (loadError || !profile) {
    return (
      <Layout>
        <h1>My Profile</h1>
        <p className="error">{loadError || 'Profile not available for this account.'}</p>
      </Layout>
    );
  }

  return (
    <Layout>
      <h1>My Profile</h1>

      <div className="card stack">
        <div className="hstack" style={{ alignItems: 'center', gap: 16 }}>
          <div
            onClick={() => fileInputRef.current?.click()}
            style={{
              width: 64, height: 64, borderRadius: '50%', overflow: 'hidden',
              background: 'var(--paper-line)', cursor: 'pointer', flexShrink: 0,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 22, fontFamily: 'var(--font-mono)', color: 'var(--muted)',
            }}
            title="Change photo"
          >
            {profile.photo_url
              ? <img src={profile.photo_url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
              : (profile.name?.[0]?.toUpperCase() || '?')}
          </div>
          <div style={{ flex: 1 }}>
            <button type="button" className="btn-ghost btn-sm" onClick={() => fileInputRef.current?.click()} disabled={photoUploading}>
              {photoUploading ? 'Uploading…' : profile.photo_url ? 'Change photo' : 'Add a photo'}
            </button>
            <input ref={fileInputRef} type="file" accept="image/png,image/jpeg" onChange={handlePhotoPick} style={{ display: 'none' }} />
            {photoError && <p className="error" style={{ margin: '4px 0 0' }}>{photoError}</p>}
          </div>
        </div>

        <div>
          <div className="row" style={{ marginBottom: 4 }}>
            <span style={{ fontSize: 12, color: 'var(--muted)' }}>Profile completion</span>
            <span style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--muted)' }}>
              {Math.round(profile.profile_completion_pct)}%
            </span>
          </div>
          <div style={{ height: 6, borderRadius: 3, background: 'var(--paper-line)', overflow: 'hidden' }}>
            <div style={{
              height: '100%', width: `${profile.profile_completion_pct}%`,
              background: 'var(--signal-red)', transition: 'width 0.3s',
            }} />
          </div>
        </div>
      </div>

      <form onSubmit={handleSave} className="card stack">
        <div>
          <label>Name</label>
          <input value={name} onChange={(e) => setName(e.target.value)} required />
        </div>
        <div>
          <label>Phone</label>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 14, color: 'var(--muted)', paddingTop: 2 }}>
            {profile.phone} <span style={{ fontSize: 12 }}>(login stays phone-based — change this from Settings)</span>
          </div>
        </div>
        <div>
          <label>Email (optional)</label>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
        </div>
        {role === 'teacher' && (
          <div>
            <label>Education (optional)</label>
            <input value={education} onChange={(e) => setEducation(e.target.value)} placeholder="e.g. B.Sc Physics, M.Ed" />
          </div>
        )}
        <div>
          <label>Bio (optional)</label>
          <textarea
            value={bio} onChange={(e) => setBio(e.target.value)} rows={4}
            placeholder={role === 'institute_admin' ? 'A short description of your institute' : 'A short line about yourself'}
          />
        </div>
        {saveError && <p className="error">{saveError}</p>}
        {saved && <p style={{ color: 'var(--ink-blue)', fontFamily: 'var(--font-mono)', fontSize: 13 }}>✓ Saved.</p>}
        <button type="submit" disabled={saving} style={{ alignSelf: 'flex-start' }}>
          {saving ? 'Saving…' : 'Save changes'}
        </button>
      </form>
    </Layout>
  );
}
