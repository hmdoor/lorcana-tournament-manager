'use strict';

// Helpers shared by the main app and the projector timer.

async function api(path, { method = 'GET', body } = {}) {
  const res = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status}).`);
  return data;
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

/** Seconds left on the round timer. `skew` = server clock minus browser clock. */
function timerSeconds(timer, skew) {
  if (!timer.running) return timer.remaining;
  return Math.max(0, timer.ends_at - (Date.now() / 1000 + skew));
}

function fmtClock(seconds) {
  const s = Math.ceil(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

/** Name for a top cut round from how many matches it has. */
function bracketRoundName(matchCount) {
  return { 1: 'Final', 2: 'Semifinals', 4: 'Quarterfinals' }[matchCount] ?? `Top ${matchCount * 2}`;
}

function roundTitle(round) {
  return round.stage === 'swiss' ? `Round ${round.number}` : bracketRoundName(round.matches.length);
}
