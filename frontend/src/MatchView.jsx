import { useEffect, useRef, useState } from 'react';
import { api } from './api';

const PLAYER_COLORS = ['#4ade80', '#60a5fa', '#fbbf24', '#f87171', '#c084fc', '#2dd4bf'];

function getTitleClass(title) {
  if (!title) return '';
  const len = title.length;
  if (len <= 10) return 'title-short';
  if (len <= 20) return 'title-medium';
  if (len <= 32) return 'title-long';
  return 'title-xlong';
}

function finishedWinner(st) {
  if (st.match.status !== 'finished') return null;
  return [...st.players].sort((a, b) => b.named_count - a.named_count)[0] || null;
}

export default function MatchView({ matchId, onBack }) {
  const [st, setSt] = useState(null);
  const [error, setError] = useState(null);
  const [guess, setGuess] = useState('');
  const [guessMsg, setGuessMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [deadline, setDeadline] = useState(null); // ms epoch when my running turn ends
  const [now, setNow] = useState(Date.now());
  const pollRef = useRef(null);

  const load = async () => {
    try {
      const data = await api(`/matches/${matchId}/state`);
      setSt(data);
      setError(null);
      const ct = data.current_turn;
      if (ct && ct.your_turn && ct.started && ct.seconds_left != null) {
        setDeadline(Date.now() + ct.seconds_left * 1000);
      } else if (ct && ct.your_turn) {
        setDeadline(null);
      }
    } catch (err) {
      setError(err.message);
    }
  };

  useEffect(() => {
    load();
    pollRef.current = setInterval(load, 8000); // poll for opponent moves
    return () => clearInterval(pollRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matchId]);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const act = async (path) => {
    setBusy(true);
    try {
      await api(`/matches/${matchId}${path}`, { method: 'POST' });
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const submitGuess = async (e) => {
    e.preventDefault();
    if (!guess.trim()) return;
    setBusy(true);
    setGuessMsg(null);
    try {
      const res = await api(`/matches/${matchId}/guess`, { method: 'POST', body: { guess } });
      if (res.correct) {
        setGuess('');
        setGuessMsg({ ok: true, text: `✅ ${res.title} — claimed!` });
      } else {
        setGuessMsg({ ok: false, text: res.message });
      }
      await load();
    } catch (err) {
      setGuessMsg({ ok: false, text: err.message });
      await load();
    } finally {
      setBusy(false);
    }
  };

  if (error && !st) {
    return (
      <div className="card">
        <div className="error">{error}</div>
        <button className="btn btn-primary" onClick={onBack}>Back to lobby</button>
      </div>
    );
  }
  if (!st) return <p className="slow-load-note">Loading match…</p>;

  const myTurn = st.current_turn?.your_turn;
  const turnStarted = st.current_turn?.started;
  const secondsLeft = deadline ? Math.max(0, Math.round((deadline - now) / 1000)) : null;

  const colorMap = {};
  [...st.players].sort((a, b) => a.turn_order - b.turn_order).forEach((p, i) => {
    colorMap[p.user_id] = PLAYER_COLORS[i % PLAYER_COLORS.length];
  });

  const finished = st.match.status === 'finished';
  const winner = finishedWinner(st);

  return (
    <div>
      <button className="link-btn back-btn" onClick={onBack}>← Lobby</button>

      <div className="card">
        <p className="label">Today's actor:</p>
        <p className="actor-name">{st.actor_name}</p>
        <p className="count">{st.total_movies} movies · {st.match.match_date}</p>
      </div>

      <div className="card scoreboard">
        {st.players.map((p) => (
          <div key={p.user_id}
               className={`player-chip ${p.status} ${st.current_turn?.user_id === p.user_id && !finished ? 'has-turn' : ''}`}
               style={{ '--pc': colorMap[p.user_id] }}>
            <span className="player-dot" />
            <span className="player-name">{p.display_name}{p.is_me ? ' (you)' : ''}</span>
            <span className="player-count">{p.named_count}</span>
            {p.status === 'resigned' && <span className="player-out">out</span>}
            {st.current_turn?.user_id === p.user_id && !finished && <span className="turn-flag">• turn</span>}
          </div>
        ))}
      </div>

      {finished ? (
        <div className="card finished-card">
          <h3>🏁 Match finished</h3>
          {winner && <p className="winner-line">🏆 <strong>{winner.display_name}</strong> wins with {winner.named_count} movies!</p>}
          <button className="btn btn-primary" onClick={onBack}>Back to lobby</button>
        </div>
      ) : myTurn ? (
        !turnStarted ? (
          <div className="card turn-card">
            <h3>It's your turn!</h3>
            <p className="hint-text">The 2-minute clock starts when you're ready.</p>
            <button className="btn btn-success btn-big" disabled={busy} onClick={() => act('/start-turn')}>
              ▶ Start My Turn
            </button>
            <button className="btn btn-giveup" disabled={busy} onClick={() => act('/resign')}>Resign</button>
          </div>
        ) : (
          <div className="card turn-card">
            <div className={`timer ${secondsLeft != null && secondsLeft <= 20 ? 'timer-low' : ''}`}>
              {secondsLeft != null ? `${secondsLeft}s` : '--'}
            </div>
            <form onSubmit={submitGuess} className="input-group">
              <input
                className="input"
                placeholder="Name a movie…"
                value={guess}
                onChange={(e) => setGuess(e.target.value)}
                autoFocus
              />
              <button className="btn btn-success" disabled={busy || !guess.trim()}>Guess</button>
              <button type="button" className="btn btn-giveup" disabled={busy} onClick={() => act('/resign')}>Resign</button>
            </form>
            {guessMsg && <div className={`guess-msg ${guessMsg.ok ? 'ok' : ''}`}>{guessMsg.text}</div>}
          </div>
        )
      ) : (
        <div className="card waiting-card">
          <p>⏳ Waiting for <strong>{st.players.find((p) => p.user_id === st.current_turn?.user_id)?.display_name || '…'}</strong> to play…</p>
          <p className="hint-text">The board updates automatically.</p>
        </div>
      )}

      {error && <div className="error">{error}</div>}

      <div className="grid">
        {Array.from({ length: st.total_movies }).map((_, index) => {
          const rank = index + 1;
          const claim = st.board[String(rank)];
          if (!claim) {
            return (
              <div key={rank} className="square">
                <span className="rank-number">{rank}</span>
              </div>
            );
          }
          const color = colorMap[claim.user_id] || '#4ade80';
          return (
            <div key={rank} className="square filled claimed" style={{ '--claim': color }}>
              <span className="claimer">({claim.by})</span>
              <span className={`movie-title ${getTitleClass(claim.title)}`} title={claim.title}>
                {claim.title}
              </span>
              <span className="movie-meta">
                {claim.year && `(${claim.year}) `}{claim.percentage}%
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}