'use strict';

const app = document.getElementById('app');

const SWISS_SCORES = [[2, 0], [2, 1], [1, 1], [1, 2], [0, 2]];
const TOPCUT_SCORES = [[2, 0], [2, 1], [1, 2], [0, 2]];
const CUT_OPTIONS = [[0, 'No top cut'], [2, 'Top 2 (final only)'], [4, 'Top 4'], [8, 'Top 8'], [16, 'Top 16'], [32, 'Top 32']];
const PHASES = { registration: 'Registration', swiss: 'Swiss rounds', topcut: 'Top cut', complete: 'Complete' };
const TABS = [
  ['players', 'Players'],
  ['pairings', 'Pairings'],
  ['standings', 'Standings'],
  ['bracket', 'Top cut'],
  ['settings', 'Settings'],
];

let current = null; // tournament view from the server
let clockSkew = 0; // server clock minus browser clock, in seconds
let tab = 'players';
let selectedRound = null; // round number shown on the Pairings tab (null = latest)
let pairingFilter = '';

// ---------------------------------------------------------------------------
// Server and routing
// ---------------------------------------------------------------------------

function setCurrent(view) {
  current = view;
  clockSkew = view.server_now - Date.now() / 1000;
}

/** Sends one change to the server and re-renders. Returns false (and shows why) if it was rejected. */
async function act(action, params = {}) {
  try {
    setCurrent(await api(`/api/tournaments/${current.id}/actions`, { method: 'POST', body: { action, ...params } }));
    renderTournament();
    return true;
  } catch (err) {
    toast(err.message);
    return false;
  }
}

async function route() {
  const [section, id, tabName] = location.hash.replace(/^#\/?/, '').split('/');
  try {
    if (section === 't' && id) {
      if (!current || current.id !== id) {
        selectedRound = null;
        pairingFilter = '';
      }
      setCurrent(await api(`/api/tournaments/${id}`));
      tab = TABS.some(([key]) => key === tabName) ? tabName : current.phase === 'registration' ? 'players' : 'pairings';
      renderTournament();
    } else {
      current = null;
      await renderHome();
    }
  } catch (err) {
    app.innerHTML = `<section class="card"><p>${esc(err.message)}</p><a href="#/">Back to tournaments</a></section>`;
  }
}

function go(tabName) {
  const target = `#/t/${current.id}/${tabName}`;
  if (location.hash === target) renderTournament();
  else location.hash = target;
}

window.addEventListener('hashchange', route);
route();

/**
 * Picks up changes made elsewhere (the projector timer, another tab). Redraws only
 * when the tournament itself changed, so typing isn't interrupted by timer updates.
 */
async function sync() {
  if (!current || document.hidden) return;
  try {
    const fresh = await api(`/api/tournaments/${current.id}`);
    if (!current || fresh.id !== current.id) return;
    const changed = JSON.stringify(fresh.tournament) !== JSON.stringify(current.tournament) || fresh.can_undo !== current.can_undo;
    const timerChanged = fresh.timer.running !== current.timer.running;
    setCurrent(fresh);
    if (changed) renderTournament();
    else if (timerChanged) document.querySelector('.timer-chip').outerHTML = timerChip(fresh);
  } catch {
    // Server briefly unreachable; try again on the next tick.
  }
}
setInterval(sync, 3000);
document.addEventListener('visibilitychange', sync);

// ---------------------------------------------------------------------------
// Lookups
// ---------------------------------------------------------------------------

function playerName(id) {
  return current.tournament.players.find((p) => p.id === id)?.name ?? 'Unknown player';
}

function standingOf(id) {
  return current.standings.find((s) => s.player_id === id);
}

function seedOf(id) {
  const i = current.tournament.top_cut?.seeds.indexOf(id) ?? -1;
  return i === -1 ? null : i + 1;
}

function outcome(result) {
  return result.p1_wins > result.p2_wins ? 'p1' : result.p2_wins > result.p1_wins ? 'p2' : 'draw';
}

function fmtScore(r) {
  return `${r.p1_wins}–${r.p2_wins}${r.draws ? `–${r.draws}` : ''}`;
}

function fmtPct(x) {
  return `${(x * 100).toFixed(2)}%`;
}

function isEditable(t, round) {
  return round === t.rounds.at(-1) || (round.stage === 'swiss' && !t.top_cut);
}

// ---------------------------------------------------------------------------
// Home
// ---------------------------------------------------------------------------

async function renderHome() {
  const list = await api('/api/tournaments');
  document.title = 'Lorcana Tournament Manager';
  app.innerHTML = `
    <section class="card">
      <h1>New tournament</h1>
      <form id="create-form" class="create-form">
        <label>Name <input name="name" placeholder="Friday Night Lorcana" required></label>
        <label>Round length (minutes) <input name="round_minutes" type="number" min="1" max="240" value="50"></label>
        <label>Top cut <select name="top_cut_size">${cutOptions(8)}</select></label>
        <button class="primary">Create tournament</button>
      </form>
    </section>
    <section class="card">
      <div class="card-head">
        <h2>Your tournaments</h2>
        <label class="button ghost">Import file…<input type="file" id="import-file" accept=".json,application/json" hidden></label>
      </div>
      ${
        list.length
          ? `<ul class="t-list">${list
              .map(
                (t) => `<li><a href="#/t/${t.id}">${esc(t.name)}</a>
                  <span class="muted small">${t.players} players · ${PHASES[t.phase]} · ${new Date(t.updated_at * 1000).toLocaleString()}</span></li>`
              )
              .join('')}</ul>`
          : '<p class="muted">No tournaments yet. Create one above.</p>'
      }
    </section>`;
}

function cutOptions(selected) {
  return CUT_OPTIONS.map(([size, label]) => `<option value="${size}" ${size === selected ? 'selected' : ''}>${label}</option>`).join('');
}

// ---------------------------------------------------------------------------
// Tournament page
// ---------------------------------------------------------------------------

function renderTournament() {
  const v = current;
  const t = v.tournament;
  document.title = `${t.name} · Lorcana`;
  const showBracket = t.settings.top_cut_size || t.top_cut;
  const tabs = TABS.filter(([key]) => key !== 'bracket' || showBracket);
  const render = { players: playersTab, pairings: pairingsTab, standings: standingsTab, bracket: bracketTab, settings: settingsTab }[tab];

  app.innerHTML = `
    <section class="t-head">
      <div>
        <a href="#/" class="back">← All tournaments</a>
        <h1>${esc(t.name)}</h1>
        <p class="muted">${statusLine(v)}</p>
      </div>
      <div class="head-tools">
        ${timerChip(v)}
        <button class="ghost" data-do="undo" ${v.can_undo ? '' : 'disabled'} title="Undo the last change">↶ Undo</button>
      </div>
    </section>
    <section class="next-step">${nextStep(v)}</section>
    <nav class="tabs">${tabs
      .map(([key, label]) => `<a href="#/t/${v.id}/${key}" class="${key === tab ? 'active' : ''}">${label}</a>`)
      .join('')}</nav>
    <section class="card tab-body">${render(v)}</section>`;
  applyFilter();
  updateTimers();
}

function statusLine(v) {
  const t = v.tournament;
  const active = t.players.filter((p) => !p.dropped).length;
  const cut = t.settings.top_cut_size ? `Top ${t.settings.top_cut_size} cut` : 'No top cut';
  return `${active} active players · ${PHASES[v.phase]} · Swiss ${v.swiss_rounds_played} of ${v.swiss_rounds_target} rounds · ${cut}`;
}

/** The single most useful next action, shown as a big button. */
function nextStep(v) {
  const t = v.tournament;
  const last = t.rounds.at(-1);
  const active = t.players.filter((p) => !p.dropped).length;
  const button = (action, label) => `<button class="primary big" data-do="${action}">${esc(label)}</button>`;

  if (v.phase === 'registration') {
    return active >= 2
      ? `${button('pair_next_round', `Start round 1 with ${active} players`)}
         <span class="muted">Recommended: ${v.recommended_swiss_rounds} Swiss rounds</span>`
      : '<span class="muted">Add at least 2 players to start round 1.</span>';
  }
  if (v.phase === 'complete') {
    return `<div class="champion">🏆 Champion: <strong>${esc(playerName(v.champion))}</strong></div>`;
  }
  const left = last.matches.filter((m) => !m.result).length;
  if (left) {
    return `<span class="waiting">${roundTitle(last)}: waiting on ${left} result${left === 1 ? '' : 's'}</span>
      ${tab === 'pairings' ? '' : `<a class="button ghost" href="#/t/${v.id}/pairings">Enter results</a>`}`;
  }
  if (v.phase === 'topcut') {
    return button('advance_top_cut', `Pair the ${bracketRoundName(last.matches.length / 2)}`);
  }
  if (v.swiss_rounds_played < v.swiss_rounds_target) {
    return button('pair_next_round', `Pair round ${v.swiss_rounds_played + 1} of ${v.swiss_rounds_target}`);
  }
  const cut = t.settings.top_cut_size;
  return `${cut ? button('start_top_cut', `Start the Top ${cut}`) : '<span class="waiting">Swiss is complete. See the final standings.</span>'}
    <button class="ghost" data-do="pair_next_round">Pair an extra Swiss round</button>`;
}

function timerChip(v) {
  const running = v.timer.running;
  return `<div class="timer-chip" title="Round timer">
    <span class="timer-readout">--:--</span>
    <button class="icon" data-do="timer" data-op="${running ? 'pause' : 'start'}" title="${running ? 'Pause' : 'Start'} the round timer">${running ? '❚❚' : '▶'}</button>
    <button class="icon" data-do="timer" data-op="reset" title="Reset the round timer">↺</button>
    <a class="icon" href="/timer?id=${v.id}" target="_blank" title="Open the big timer for a projector">⛶</a>
  </div>`;
}

function updateTimers() {
  if (!current) return;
  const seconds = timerSeconds(current.timer, clockSkew);
  for (const el of document.querySelectorAll('.timer-readout')) {
    el.textContent = seconds > 0 ? fmtClock(seconds) : 'Time!';
    el.classList.toggle('expired', seconds <= 0);
  }
}
setInterval(updateTimers, 250);

// ----- Players tab -----

function playersTab(v) {
  const t = v.tournament;
  const players = [...t.players].sort((a, b) => a.name.localeCompare(b.name));
  const locked = Boolean(t.top_cut);
  const rows = players
    .map((p) => {
      const s = standingOf(p.id);
      const status = p.dropped
        ? `<span class="tag">Dropped after round ${p.dropped_after_round}</span>`
        : p.joined_round > 1
          ? `<span class="tag gold">Joined in round ${p.joined_round}</span>`
          : '<span class="muted">Active</span>';
      const data = `data-player="${p.id}" data-name="${esc(p.name)}"`;
      const actions = [
        `<button class="link" data-do="rename" ${data}>Rename</button>`,
        v.phase === 'registration'
          ? `<button class="link danger" data-do="remove" ${data}>Remove</button>`
          : p.dropped
            ? `<button class="link" data-do="reinstate" ${data}>Undo drop</button>`
            : `<button class="link danger" data-do="drop" ${data}>Drop</button>`,
      ].join(' ');
      return `<tr class="${p.dropped ? 'dropped' : ''}">
        <td>${esc(p.name)}</td><td>${s.wins}–${s.losses}–${s.draws}</td><td>${status}</td><td class="actions">${actions}</td></tr>`;
    })
    .join('');

  return `
    <form id="add-player" class="row">
      <input id="new-player" name="name" placeholder="Player name" autocomplete="off" ${locked ? 'disabled' : ''} required>
      <button class="primary" ${locked ? 'disabled' : ''}>Add player</button>
      <button type="button" class="ghost" data-do="toggle-bulk" ${locked ? 'disabled' : ''}>Paste a list…</button>
    </form>
    <form id="add-bulk" class="bulk" hidden>
      <textarea name="names" rows="6" placeholder="One name per line"></textarea>
      <button class="primary">Add all</button>
    </form>
    ${v.phase === 'swiss' ? '<p class="muted small">Players added now take a loss for each round already paired.</p>' : ''}
    ${
      players.length
        ? `<table class="data"><thead><tr><th>Player (${players.length})</th><th>Record</th><th>Status</th><th></th></tr></thead><tbody>${rows}</tbody></table>`
        : '<p class="muted">No players yet.</p>'
    }`;
}

// ----- Pairings tab -----

function pairingsTab(v) {
  const t = v.tournament;
  if (!t.rounds.length) return '<p class="muted">No rounds yet. Add players, then start round 1.</p>';
  const round = t.rounds.find((r) => r.number === selectedRound) ?? t.rounds.at(-1);
  const editable = isEditable(t, round);
  const done = round.matches.filter((m) => m.result).length;

  return `
    <div class="round-picker">${t.rounds
      .map((r) => `<button class="chip ${r === round ? 'active' : ''}" data-do="round" data-round="${r.number}">${roundTitle(r)}</button>`)
      .join('')}</div>
    <div class="card-head">
      <h2>${roundTitle(round)} <span class="muted small">${done} of ${round.matches.length} reported</span></h2>
      <div class="row">
        <input id="match-filter" type="search" placeholder="Find a player…" value="${esc(pairingFilter)}">
        <button class="ghost" data-do="print-pairings" data-round="${round.number}">Print pairings</button>
      </div>
    </div>
    <p class="muted small">${
      editable
        ? 'Tap the score in games won, left player first. Use “Other” for scores like 1–0 when time is called.'
        : 'This round is locked because later rounds have been paired. Use Undo to go back.'
    }</p>
    <div class="matches">${round.matches.map((m) => matchCard(m, round, editable)).join('')}</div>`;
}

function matchCard(m, round, editable) {
  const searchable = esc(`${playerName(m.p1)} ${m.p2 ? playerName(m.p2) : ''}`.toLowerCase());
  if (!m.p2) {
    return `<div class="match done bye" data-names="${searchable}">
      <div class="table-no">Bye</div>
      <div class="side left win">${esc(playerName(m.p1))}</div>
      <div class="scores muted small">Counts as a 2–0 win</div>
      <div class="side right"></div>
    </div>`;
  }
  const winner = m.result ? outcome(m.result) : null;
  const scores = round.stage === 'swiss' ? SWISS_SCORES : TOPCUT_SCORES;
  const isSelected = ([a, b]) => m.result && m.result.p1_wins === a && m.result.p2_wins === b && !m.result.draws;
  const custom = m.result && !scores.some(isSelected);
  const disabled = editable ? '' : 'disabled';
  const tag = (id) =>
    round.stage === 'swiss' ? `<small>${standingOf(id).match_points} pts</small>` : `<small>Seed ${seedOf(id)}</small>`;

  return `<div class="match ${m.result ? 'done' : ''}" data-names="${searchable}">
    <div class="table-no">Table ${m.table}</div>
    <div class="side left ${winner === 'p1' ? 'win' : ''}">${esc(playerName(m.p1))} ${tag(m.p1)}</div>
    <div class="scores">
      ${scores
        .map(
          ([a, b]) => `<button class="score ${isSelected([a, b]) ? 'selected' : ''}" data-do="report" data-match="${m.id}"
            data-p1="${a}" data-p2="${b}" ${disabled}>${a}–${b}</button>`
        )
        .join('')}
      <button class="score ${custom ? 'selected' : ''}" data-do="custom-score" data-match="${m.id}" ${disabled}>${custom ? fmtScore(m.result) : 'Other'}</button>
      ${m.result && editable ? `<button class="link" data-do="clear" data-match="${m.id}">Clear</button>` : ''}
    </div>
    <div class="side right ${winner === 'p2' ? 'win' : ''}">${esc(playerName(m.p2))} ${tag(m.p2)}</div>
  </div>`;
}

function applyFilter() {
  const q = pairingFilter.trim().toLowerCase();
  for (const el of document.querySelectorAll('.match')) el.hidden = Boolean(q) && !el.dataset.names.includes(q);
}

// ----- Standings tab -----

function standingsTab(v) {
  if (!v.standings.length) return '<p class="muted">No players yet.</p>';
  return `
    <div class="card-head">
      <h2>Swiss standings</h2>
      <button class="ghost" data-do="print-standings">Print standings</button>
    </div>
    <p class="muted small">Ties are broken by opponents’ match win % (OMW), then game win % (GW), then opponents’ game win % (OGW).
      ${cutSize(v) ? 'Players inside the top cut are marked in gold.' : ''}</p>
    ${standingsTable(v)}`;
}

function cutSize(v) {
  return v.tournament.top_cut?.size ?? v.tournament.settings.top_cut_size;
}

function standingsTable(v) {
  const cut = cutSize(v);
  let activeSeen = 0;
  const rows = v.standings
    .map((s) => {
      const inCut = !s.dropped && cut && ++activeSeen <= cut;
      return `<tr class="${s.dropped ? 'dropped' : ''} ${inCut ? 'in-cut' : ''}">
        <td>${s.rank}</td>
        <td>${esc(s.name)}${s.dropped ? ' <span class="tag">Dropped</span>' : ''}</td>
        <td class="num"><strong>${s.match_points}</strong></td>
        <td class="num">${s.wins}–${s.losses}–${s.draws}</td>
        <td class="num">${fmtPct(s.opp_match_win_pct)}</td>
        <td class="num">${fmtPct(s.game_win_pct)}</td>
        <td class="num">${fmtPct(s.opp_game_win_pct)}</td>
      </tr>`;
    })
    .join('');
  return `<table class="data standings"><thead><tr>
      <th>#</th><th>Player</th><th class="num">Points</th><th class="num">W–L–D</th>
      <th class="num">OMW</th><th class="num">GW</th><th class="num">OGW</th>
    </tr></thead><tbody>${rows}</tbody></table>`;
}

// ----- Top cut tab -----

function bracketTab(v) {
  const t = v.tournament;
  if (!t.top_cut) {
    return `<p class="muted">${
      t.settings.top_cut_size ? `The Top ${t.settings.top_cut_size} bracket appears here once Swiss is finished.` : 'There is no top cut. You can add one in Settings.'
    }</p>`;
  }
  const played = t.rounds.filter((r) => r.stage === 'topcut');
  const columns = [];
  for (let count = t.top_cut.size / 2, i = 0; count >= 1; count /= 2, i++) {
    columns.push(played[i]?.matches ?? Array(count).fill(null));
  }
  const champ = v.champion
    ? `<div class="b-col"><h3>Champion</h3><div class="b-match champ"><div class="b-slot win">🏆 ${esc(playerName(v.champion))}</div></div></div>`
    : '';
  return `<div class="bracket">${columns
    .map((matches) => `<div class="b-col"><h3>${bracketRoundName(matches.length)}</h3>${matches.map(bracketMatch).join('')}</div>`)
    .join('')}${champ}</div>`;
}

function bracketMatch(m) {
  if (!m) return '<div class="b-match"><div class="b-slot muted">TBD</div><div class="b-slot muted">TBD</div></div>';
  const winner = m.result ? outcome(m.result) : null;
  const slot = (id, side, games) =>
    `<div class="b-slot ${winner === side ? 'win' : winner ? 'lose' : ''}">
      <span class="seed">${seedOf(id)}</span><span class="b-name">${esc(playerName(id))}</span><span class="games">${m.result ? games : ''}</span>
    </div>`;
  return `<div class="b-match">${slot(m.p1, 'p1', m.result?.p1_wins)}${slot(m.p2, 'p2', m.result?.p2_wins)}</div>`;
}

// ----- Settings tab -----

function settingsTab(v) {
  const t = v.tournament;
  const s = t.settings;
  const roundOptions = Array.from({ length: 15 }, (_, i) => i + 1)
    .map((n) => `<option value="${n}" ${s.swiss_rounds === n ? 'selected' : ''}>${n}</option>`)
    .join('');
  return `
    <form id="settings-form" class="settings">
      <label>Tournament name <input name="name" value="${esc(t.name)}" required></label>
      <label>Round length (minutes) <input name="round_minutes" type="number" min="1" max="240" value="${s.round_minutes}"></label>
      <label>Swiss rounds
        <select name="swiss_rounds">
          <option value="" ${s.swiss_rounds === null ? 'selected' : ''}>Automatic (${v.recommended_swiss_rounds} for ${t.players.length} players)</option>
          ${roundOptions}
        </select>
      </label>
      <label>Top cut
        <select name="top_cut_size" ${t.top_cut ? 'disabled title="The top cut has started"' : ''}>${cutOptions(s.top_cut_size)}</select>
      </label>
      <div><button class="primary">Save settings</button></div>
    </form>
    <hr>
    <h2>Backup</h2>
    <p class="muted">Download this event as a file to back it up or move it to another computer. Use “Import file” on the home page to load it.</p>
    <a class="button ghost" href="/api/tournaments/${v.id}/export" download>Export tournament file</a>
    <hr>
    <h2>Delete</h2>
    <p class="muted">Deleted tournaments are moved to the “deleted” folder inside the app’s data folder, not erased.</p>
    <button class="danger" data-do="delete">Delete tournament</button>`;
}

// ---------------------------------------------------------------------------
// Printing
// ---------------------------------------------------------------------------

function printHtml(html) {
  document.getElementById('print').innerHTML = html;
  window.print();
}

/** Alphabetical by player, so people can find their table on a printed sheet. */
function printPairings(roundNumber) {
  const t = current.tournament;
  const round = t.rounds.find((r) => r.number === roundNumber);
  const rows = [];
  for (const m of round.matches) {
    rows.push([playerName(m.p1), m.table ?? '—', m.p2 ? playerName(m.p2) : 'BYE']);
    if (m.p2) rows.push([playerName(m.p2), m.table, playerName(m.p1)]);
  }
  rows.sort((a, b) => a[0].localeCompare(b[0]));
  printHtml(`<h1>${esc(t.name)}: ${roundTitle(round)} pairings</h1>
    <table class="data"><thead><tr><th>Player</th><th>Table</th><th>Opponent</th></tr></thead>
    <tbody>${rows.map((r) => `<tr><td>${esc(r[0])}</td><td>${r[1]}</td><td>${esc(r[2])}</td></tr>`).join('')}</tbody></table>`);
}

// ---------------------------------------------------------------------------
// Events
// ---------------------------------------------------------------------------

app.addEventListener('click', async (e) => {
  const el = e.target.closest('[data-do]');
  if (!el) return;
  const d = el.dataset;

  switch (d.do) {
    case 'pair_next_round':
    case 'start_top_cut':
    case 'advance_top_cut':
      selectedRound = null;
      if (await act(d.do)) go('pairings');
      break;
    case 'undo':
      selectedRound = null;
      await act('undo');
      break;
    case 'timer':
      await act(`timer_${d.op}`);
      break;
    case 'round':
      selectedRound = Number(d.round);
      renderTournament();
      break;
    case 'report':
      await act('report_result', { match_id: d.match, p1_wins: Number(d.p1), p2_wins: Number(d.p2), draws: 0 });
      break;
    case 'custom-score': {
      const text = prompt('Enter games won by the left player, then the right player, then any drawn games.\nExamples: 1-0   1-0-1   0-0', '');
      if (!text) break;
      const nums = text.split(/[^0-9]+/).filter(Boolean).map(Number);
      if (nums.length < 2 || nums.length > 3) {
        toast('Enter two or three numbers, like 1-0 or 1-0-1.');
        break;
      }
      await act('report_result', { match_id: d.match, p1_wins: nums[0], p2_wins: nums[1], draws: nums[2] ?? 0 });
      break;
    }
    case 'clear':
      await act('clear_result', { match_id: d.match });
      break;
    case 'toggle-bulk':
      document.getElementById('add-bulk').hidden ^= true;
      break;
    case 'rename': {
      const name = prompt('New name', d.name);
      if (name && name.trim() && name.trim() !== d.name) await act('rename_player', { player_id: d.player, name });
      break;
    }
    case 'remove':
      if (confirm(`Remove ${d.name} from the tournament?`)) await act('remove_player', { player_id: d.player });
      break;
    case 'drop':
      if (confirm(`Drop ${d.name}? They won’t be paired in future rounds.`)) await act('drop_player', { player_id: d.player });
      break;
    case 'reinstate':
      await act('reinstate_player', { player_id: d.player });
      break;
    case 'print-pairings':
      printPairings(Number(d.round));
      break;
    case 'print-standings':
      printHtml(`<h1>${esc(current.tournament.name)}: standings</h1>${standingsTable(current)}`);
      break;
    case 'delete':
      if (!confirm(`Delete “${current.tournament.name}”?`)) break;
      try {
        await api(`/api/tournaments/${current.id}`, { method: 'DELETE' });
        location.hash = '#/';
      } catch (err) {
        toast(err.message);
      }
      break;
  }
});

app.addEventListener('submit', async (e) => {
  e.preventDefault();
  const form = e.target;
  const data = Object.fromEntries(new FormData(form));

  switch (form.id) {
    case 'create-form':
      try {
        const view = await api('/api/tournaments', {
          method: 'POST',
          body: { name: data.name, round_minutes: Number(data.round_minutes), top_cut_size: Number(data.top_cut_size) },
        });
        setCurrent(view);
        location.hash = `#/t/${view.id}/players`;
      } catch (err) {
        toast(err.message);
      }
      break;
    case 'add-player':
      if (await act('add_player', { name: data.name })) document.getElementById('new-player')?.focus();
      break;
    case 'add-bulk':
      await act('add_players', { names: data.names });
      break;
    case 'settings-form': {
      const body = {
        name: data.name,
        round_minutes: Number(data.round_minutes),
        swiss_rounds: data.swiss_rounds ? Number(data.swiss_rounds) : null,
      };
      if ('top_cut_size' in data) body.top_cut_size = Number(data.top_cut_size);
      if (await act('update_settings', body)) toast('Settings saved.', 'ok');
      break;
    }
  }
});

app.addEventListener('input', (e) => {
  if (e.target.id === 'match-filter') {
    pairingFilter = e.target.value;
    applyFilter();
  }
});

app.addEventListener('change', async (e) => {
  if (e.target.id !== 'import-file') return;
  const file = e.target.files[0];
  if (!file) return;
  try {
    const view = await api('/api/import', { method: 'POST', body: JSON.parse(await file.text()) });
    setCurrent(view);
    location.hash = `#/t/${view.id}/players`;
  } catch (err) {
    toast(err instanceof SyntaxError ? 'That file isn’t a valid tournament export.' : err.message);
  }
});

// ---------------------------------------------------------------------------
// Toast messages
// ---------------------------------------------------------------------------

let toastTimer = null;
function toast(message, kind = 'error') {
  const el = document.getElementById('toast');
  el.textContent = message;
  el.className = `show ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.className = ''), 4000);
}
