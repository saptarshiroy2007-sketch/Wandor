import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { login } from '../api/client';

export default function Login() {
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(phone, password);
      navigate('/');
    } catch {
      setError('Wrong phone number or password');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-cream flex items-center justify-center px-4">
      <div className="w-full max-w-sm bg-white rounded-xl border border-black/5 px-6 py-8">
        {/* Wordmark */}
        <div className="text-center mb-6">
          <h1 className="font-display text-3xl font-semibold text-ink tracking-tight">
            Wandor
          </h1>
          <p className="text-sm text-ink/50 mt-1">Sign in to your dashboard</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="phone" className="sr-only">
              Phone number
            </label>
            <input
              id="phone"
              type="tel"
              placeholder="Phone number"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              required
              className="w-full rounded-lg border border-black/10 px-3.5 py-2.5 text-sm text-ink placeholder:text-ink/40 focus:outline-none focus:ring-2 focus:ring-teal-600/30 focus:border-teal-600"
            />
          </div>
          <div>
            <label htmlFor="password" className="sr-only">
              Password
            </label>
            <input
              id="password"
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="w-full rounded-lg border border-black/10 px-3.5 py-2.5 text-sm text-ink placeholder:text-ink/40 focus:outline-none focus:ring-2 focus:ring-teal-600/30 focus:border-teal-600"
            />
          </div>

          {error && (
            <p className="text-sm text-red-600 font-medium">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-lg bg-teal-800 text-white text-sm font-medium py-2.5 hover:bg-teal-900 disabled:opacity-60 transition-colors"
          >
            {loading ? 'Logging in…' : 'Log in'}
          </button>
        </form>
      </div>
    </div>
  );
}

