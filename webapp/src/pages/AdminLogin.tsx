import ThemeToggle from '../components/ThemeToggle';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { adminLogin } from '../api/client';

export default function AdminLogin() {
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const navigate = useNavigate();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    try {
      await adminLogin(phone, password);
      navigate('/admin');
    } catch (err: any) {
      const status = err?.response?.status;
      const detail = err?.response?.data?.detail;
      if (status === 429) setError('Too many attempts. Try again in a minute.');
      else if (status === 401) setError('Wrong phone number or password');
      else if (typeof detail === 'string' && detail) setError(detail);
      else if (!err?.response) setError('Could not reach the server. Try again.');
      else setError('Something went wrong. Try again.');
    }
  }

  return (
    <div className="page" style={{ maxWidth: 360, paddingTop: '15vh' }}>
      <div style={{ position: 'fixed', top: 12, right: 12 }}><ThemeToggle /></div>
      <div className="brand" style={{ justifyContent: 'center', marginBottom: 4 }}>
        <span className="brand-mark">W</span>
        <span className="brand-word" style={{ fontSize: 26 }}>Wandor</span>
      </div>
      <p>Platform admin login</p>
      <form onSubmit={handleSubmit} className="card stack">
        <input placeholder="Phone" value={phone} onChange={(e) => setPhone(e.target.value)} />
        <input placeholder="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        {error && <p className="error">{error}</p>}
        <button type="submit">Log in</button>
      </form>
    </div>
  );
}
