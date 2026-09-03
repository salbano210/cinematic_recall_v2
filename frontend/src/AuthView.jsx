import { useState } from 'react';
import { api, saveToken } from './api';

export default function AuthView({ onAuthed }) {
  const [mode, setMode] = useState('login'); // login | register
  const [email, setEmail] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const path = mode === 'login' ? '/auth/login' : '/auth/register';
      const body = mode === 'login'
        ? { email, password }
        : { email, display_name: displayName, password };
      const res = await api(path, { method: 'POST', body });
      saveToken(res.token);
      onAuthed(res.user);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card auth-card">
      <h2 className="subtitle">{mode === 'login' ? 'Welcome back' : 'Join the crew'}</h2>
      <form onSubmit={submit} className="auth-form">
        {mode === 'register' && (
          <input
            className="input"
            placeholder="Your name (as friends will see it)"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            required
            minLength={2}
            maxLength={60}
          />
        )}
        <input
          className="input"
          type="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <input
          className="input"
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          minLength={6}
        />
        {error && <div className="error">{error}</div>}
        <button className="btn btn-primary" disabled={busy}>
          {busy ? '...' : mode === 'login' ? 'Log In' : 'Create Account'}
        </button>
      </form>
      <p className="auth-switch">
        {mode === 'login' ? "New here? " : 'Already have an account? '}
        <button className="link-btn" onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(null); }}>
          {mode === 'login' ? 'Create an account' : 'Log in'}
        </button>
        <span className="auth-note"> — one time only, you stay logged in</span>
      </p>
    </div>
  );
}
