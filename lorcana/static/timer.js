'use strict';

// Projector timer. Polls the server so it stays in sync with controls on the main screen.

const tournamentId = new URLSearchParams(location.search).get('id');
const clock = document.getElementById('tp-clock');
const toggle = document.getElementById('tp-toggle');
const controls = document.getElementById('tp-controls');
let view = null;
let skew = 0;

function setView(next) {
  view = next;
  skew = next.server_now - Date.now() / 1000;
  const last = next.tournament.rounds.at(-1);
  document.getElementById('tp-title').textContent = next.tournament.name;
  document.getElementById('tp-round').textContent = last ? roundTitle(last) : 'Starting soon';
  document.title = `Timer · ${next.tournament.name}`;
  tick();
}

async function refresh() {
  try {
    setView(await api(`/api/tournaments/${tournamentId}`));
  } catch (err) {
    document.getElementById('tp-round').textContent = err.message;
  }
}

async function send(op, seconds) {
  if (op === 'fullscreen') return toggleFullscreen();
  try {
    setView(await api(`/api/tournaments/${tournamentId}/actions`, { method: 'POST', body: { action: `timer_${op}`, seconds } }));
  } catch (err) {
    document.getElementById('tp-round').textContent = err.message;
  }
}

function tick() {
  if (!view) return;
  const seconds = timerSeconds(view.timer, skew);
  clock.textContent = seconds > 0 ? fmtClock(seconds) : 'TIME';
  clock.classList.toggle('expired', seconds <= 0);
  clock.classList.toggle('paused', !view.timer.running && seconds > 0);
  toggle.textContent = view.timer.running ? 'Pause' : 'Start';
  toggle.dataset.op = view.timer.running ? 'pause' : 'start';
}

function toggleFullscreen() {
  if (document.fullscreenElement) document.exitFullscreen();
  else document.documentElement.requestFullscreen?.();
}

controls.addEventListener('click', (e) => {
  const button = e.target.closest('button');
  if (button) send(button.dataset.op, button.dataset.seconds ? Number(button.dataset.seconds) : undefined);
});

document.addEventListener('keydown', (e) => {
  if (e.key === ' ') send(view?.timer.running ? 'pause' : 'start');
  else if (e.key === 'ArrowUp') send('add', 60);
  else if (e.key === 'ArrowDown') send('add', -60);
  else if (e.key === 'f' || e.key === 'F') toggleFullscreen();
  else return;
  e.preventDefault();
});

// Hide the controls when the mouse is still, so the projector shows only the clock.
let idleTimer = null;
function wake() {
  controls.classList.remove('idle');
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => controls.classList.add('idle'), 3000);
}
document.addEventListener('mousemove', wake);
wake();

refresh();
setInterval(refresh, 2000);
setInterval(tick, 200);
