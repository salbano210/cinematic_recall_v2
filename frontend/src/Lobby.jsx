import { useState } from 'react';
import { api } from './api';

function toggleWith(setter, id) {
  setter((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
}

export default function Lobby({ user, onOpenMatch, onLogout }) {
  const [matches, setMatches] = useState(null);
  const [crew, setCrew] = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [error, setError] = useState(null);
  const [creating, setCreating] = useState(false);
  const [inviteCode, setInviteCode] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [createdInvite, setCreatedInvite] = useState(null);

  const load = async () => {
    try {
      const [ms, c] = await Promise.all([api('/matches'), api('/auth/crew')]);
      setMatches(ms);
      setCrew(c);
    } catch (err) {
      setError(err.message);
    }
  };

  useState(() => { load(); });

  const toggleCrew = (id) => toggleWith(setSelected, id);

  const createMatch = async () => {
    setCreating(true);
    setError(null);
    try {
      const res = await api('/matches', {
        method: 'POST',
        body: { crew_user_ids: [...selected] },
      });
      setCreatedInvite(`${window.location.origin}/?invite=${res.invite_token}`);
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setCreating(false);
    }
  };

  const joinByInvite = async () => {
    setError(null);
    try {
      const token = inviteCode.includes('invite=')
        ? new URL(inviteCode).searchParams.get('invite')
        : inviteCode.trim();
      const res = await api(`/matches/join/${encodeURIComponent(token)}`, { method: 'POST' });
      onOpenMatch(res.match_id);
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div>
      <div className="card lobby-header">
        <div className="lobby-user">
          <span className="actor-name">{user.display_name}</span>
          <button className="link-btn" onClick={onLogout}>Log out</button>
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      {createdInvite && (
        <div className="card invite-card">
          <h3>🎬 Match created!</h3>
          <p>Share this link with anyone new (your crew is already in):</p>
          <code className="invite-link">{createdInvite}</code>
          <button className="btn btn-success" onClick={() => navigator.clipboard?.writeText(createdInvite)}>
            Copy invite link
          </button>
        </div>
      )}

      {matches && matches.some((m) => m.your_turn) && (
        <div className="card">
          <h3 className="section-title">🔔 Your turn</h3>
          {matches.filter((m) => m.your_turn).map((m) => (
            <button key={m.match_id} className="btn btn-turn" onClick={() => onOpenMatch(m.match_id)}>
              {m.awaiting_start ? '▶ Start your turn' : '⏱ Your turn is running!'} — {m.match_date}
            </button>
          ))}
        </div>
      )}

      <div className="card">
        <h3 className="section-title">All matches</h3>
        {!matches && <p className="slow-load-note">Loading…</p>}
        {matches && matches.length === 0 && (
          <p className="hint-text">No matches yet — create the first one below.</p>
        )}
        {matches && matches.length > 0 && (
          <ul className="match-list">
            {matches.map((m) => (
              <li key={m.match_id}>
                <button className="match-row" onClick={() => onOpenMatch(m.match_id)}>
                  <span>{m.match_date}</span>
                  <span className={`match-status ${m.status}`}>
                    {m.status === 'finished' ? 'Finished' : m.your_turn ? 'YOUR TURN' : 'Waiting'}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="card">
        <h3 className="section-title">Start a new match</h3>
        {!showCreate ? (
          <>
            <p className="hint-text">Today's actor. Friends join anytime via your invite link.</p>
            <button className="btn btn-primary" onClick={() => { setShowCreate(true); load(); }}>＋ New match</button>
          </>
        ) : (
          <>
            {crew.length === 0 ? (
              <p className="hint-text">
                Your crew is empty — start the match and share the invite link.
                Anyone who joins is in your crew for every future game.
              </p>
            ) : (
              <>
                <p className="hint-text">Select opponents (or start solo — friends can join via the invite link):</p>
                {crew.map((c) => (
                  <label key={c.id} className="crew-row">
                    <input
                      type="checkbox"
                      checked={selected.has(c.id)}
                      onChange={() => toggleCrew(c.id)}
                    />
                    {c.display_name}
                  </label>
                ))}
              </>
            )}
            <button className="btn btn-success" onClick={createMatch} disabled={creating}>
              {creating ? 'Creating…' : 'Start match'}
            </button>
          </>
        )}
      </div>

      <div className="card">
        <h3 className="section-title">Join with an invite</h3>
        <div className="input-group">
          <input
            className="input"
            placeholder="Paste invite link or code"
            value={inviteCode}
            onChange={(e) => setInviteCode(e.target.value)}
          />
          <button className="btn btn-primary" onClick={joinByInvite} disabled={!inviteCode.trim()}>
            Join
          </button>
        </div>
      </div>
    </div>
  );
}
