import { useEffect, useState } from 'react';
import './App.css';
import { api, getToken, clearToken } from './api';
import AuthView from './AuthView';
import Lobby from './Lobby';
import MatchView from './MatchView';

export default function App() {
  const [user, setUser] = useState(null);       // logged-in user (null = auth screen)
  const [booting, setBooting] = useState(true);
  const [activeMatchId, setActiveMatchId] = useState(null);

  // On load: warm the backend, restore session, handle ?invite= / ?match= deep links
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const invite = params.get('invite');
    const match = params.get('match');
    if (invite) {
      sessionStorage.setItem('cr2_invite', invite);
      window.history.replaceState({}, '', '/');
    } else if (match) {
      sessionStorage.setItem('cr2_match', match);
      window.history.replaceState({}, '', '/');
    }
    // Wake the backend (Render free tier cold start)
    fetch(`${import.meta.env.VITE_BACKEND_URL}/`).catch(() => {});

    const restore = async () => {
      if (getToken()) {
        try {
          const me = await api('/auth/me');
          setUser(me);
        } catch {
          clearToken();
        }
      }
      setBooting(false);
    };
    restore();
  }, []);

  // After login: auto-join an invite or open a linked match
  useEffect(() => {
    if (!user) return;
    const inviteToken = sessionStorage.getItem('cr2_invite');
    const matchId = sessionStorage.getItem('cr2_match');
    sessionStorage.removeItem('cr2_invite');
    sessionStorage.removeItem('cr2_match');
    if (inviteToken) {
      api(`/matches/join/${encodeURIComponent(inviteToken)}`, { method: 'POST' })
        .then((res) => setActiveMatchId(res.match_id))
        .catch(() => {});
    } else if (matchId) {
      setActiveMatchId(matchId);
    }
  }, [user]);

  const handleLogout = () => {
    clearToken();
    setUser(null);
    setActiveMatchId(null);
  };

  if (booting) {
    return <p className="slow-load-note">Loading…</p>;
  }

  if (!user) {
    return (
      <div className="app">
        <div className="container">
          <h1 className="title">🎬 Cinematic Recall</h1>
          <p className="tagline">Pass-and-play movie naming against your friends.</p>
          <AuthView onAuthed={setUser} />
        </div>
      </div>
    );
  }

  return (
    <div className="app">
      <div className="container">
        <h1 className="title title-small">🎬 Cinematic Recall</h1>
        {activeMatchId ? (
          <MatchView matchId={activeMatchId} onBack={() => setActiveMatchId(null)} />
        ) : (
          <Lobby user={user} onOpenMatch={setActiveMatchId} onLogout={handleLogout} />
        )}
      </div>
    </div>
  );
}