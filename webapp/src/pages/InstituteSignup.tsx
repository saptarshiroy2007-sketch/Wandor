import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { instituteSignup } from '../api/client';

// Replaces the old manual DB-insert + scripts/set_institute_password.py bootstrap -
// this creates the Institute row and activates its login password in one step.
export default function InstituteSignup() {
  const [name, setName] = useState('');
  const [ownerPhone, setOwnerPhone] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const navigate = useNavigate();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    try {
      await instituteSignup(name, ownerPhone, password);
      navigate('/institute');
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Could not sign up');
    }
  }

  return (
    <div className="page" style={{ maxWidth: 360, paddingTop: '15vh' }}>
      <h1>Wandor</h1>
      <p>Institute sign up</p>
      <form onSubmit={handleSubmit} className="card stack">
        <input placeholder="Institute name" value={name} onChange={(e) => setName(e.target.value)} />
        <input placeholder="Owner phone" value={ownerPhone} onChange={(e) => setOwnerPhone(e.target.value)} />
        <input placeholder="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        {error && <p className="error">{error}</p>}
        <button type="submit">Sign up</button>
      </form>
      <p className="hstack" style={{ justifyContent: 'center', marginTop: 16 }}>
        <Link to="/institute-login">Already have an account? Log in</Link>
      </p>
      <p className="hstack" style={{ justifyContent: 'center', marginTop: 4 }}>
        <Link to="/">Back</Link>
      </p>
    </div>
  );
}
