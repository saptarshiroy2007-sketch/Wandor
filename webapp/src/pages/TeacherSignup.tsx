import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { teacherSignup } from '../api/client';

// Independent teacher signup only - there's no institute field on this form on
// purpose. Joining an institute later happens when an institute admin adds you
// (see InstituteDashboard's "add teacher" flow), not something you self-attach to
// here. Students never get an equivalent page - only a teacher or institute admin
// can create a student login.
export default function TeacherSignup() {
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const navigate = useNavigate();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    try {
      await teacherSignup(name, phone, password);
      navigate('/');
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Could not sign up');
    }
  }

  return (
    <div className="page" style={{ maxWidth: 360, paddingTop: '15vh' }}>
      <div className="brand" style={{ justifyContent: 'center', marginBottom: 4 }}>
        <span className="brand-mark">W</span>
        <span className="brand-word" style={{ fontSize: 26 }}>Wandor</span>
      </div>
      <p>Teacher sign up (independent)</p>
      <form onSubmit={handleSubmit} className="card stack">
        <input placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} />
        <input placeholder="Phone" value={phone} onChange={(e) => setPhone(e.target.value)} />
        <input placeholder="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        {error && <p className="error">{error}</p>}
        <button type="submit">Sign up</button>
      </form>
      <p className="hstack" style={{ justifyContent: 'center', marginTop: 16 }}>
        <Link to="/login">Already have an account? Log in</Link>
      </p>
      <p className="hstack" style={{ justifyContent: 'center', marginTop: 4 }}>
        <Link to="/">Back</Link>
      </p>
    </div>
  );
}
