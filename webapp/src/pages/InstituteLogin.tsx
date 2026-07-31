import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { instituteLogin } from '../api/client';

export default function InstituteLogin() {
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const navigate = useNavigate();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    try {
      await instituteLogin(phone, password);
      navigate('/institute');
    } catch {
      setError('Wrong phone number or password');
    }
  }

  return (
    <div className="page" style={{ maxWidth: 360, paddingTop: '15vh' }}>
      <h1>Wandor</h1>
      <p>Institute owner login</p>
      <form onSubmit={handleSubmit} className="card stack">
        <input placeholder="Phone" value={phone} onChange={(e) => setPhone(e.target.value)} />
        <input placeholder="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        {error && <p className="error">{error}</p>}
        <button type="submit">Log in</button>
      </form>
      <p className="hstack" style={{ justifyContent: 'center', marginTop: 16 }}>
        <Link to="/">Back</Link>
      </p>
    </div>
  );
}
