import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { studentLogin } from '../api/client';

export default function StudentLogin() {
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const navigate = useNavigate();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    try {
      await studentLogin(phone, password);
      navigate('/home');
    } catch {
      // Covers both wrong credentials AND a student whose login was never activated
      // (hashed_password is null until a teacher sets one via POST /students or
      // POST /students/{id}/set-password) - same 401 either way, so same message.
      setError('Wrong phone number or PIN. If you\u2019ve never logged in before, ask your teacher to set your PIN.');
    }
  }

  return (
    <div className="page" style={{ maxWidth: 360, paddingTop: '15vh' }}>
      <h1>Wandor</h1>
      <p>Student login</p>
      <form onSubmit={handleSubmit} className="card stack">
        <input placeholder="Phone" value={phone} onChange={(e) => setPhone(e.target.value)} />
        <input placeholder="PIN" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        {error && <p className="error">{error}</p>}
        <button type="submit">Log in</button>
      </form>
      <p className="hstack" style={{ justifyContent: 'center', marginTop: 16 }}>
        <Link to="/login">Teacher login</Link> · <Link to="/parent-login">Parent login</Link>
      </p>
    </div>
  );
}
