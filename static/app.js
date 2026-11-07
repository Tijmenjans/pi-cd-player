let state = null;
let busy = false;
let pendingSource = null;
let sourceRevision = 0;
let desiredSource = null;
let polling = null;
let failed = 0;
let lastTracks = '';
let lastStatusAt = 0;
let noticeTimer;
let coverURL = '';
const $ = id => document.getElementById(id);
const text = (id, value) => { $(id).textContent = value ?? ''; };
const show = (id, visible) => {
  if (visible) $(id).removeAttribute('hidden');
  else $(id).setAttribute('hidden', '');
};
const duration = value => {
  const seconds = Math.max(0, Math.floor(Number(value) || 0));
  return Math.floor(seconds / 60) + ':' + String(seconds % 60).padStart(2, '0');
};

function notice(message) {
  text('notice', message);
  clearTimeout(noticeTimer);
  if (message) noticeTimer = setTimeout(() => text('notice', ''), 10000);
}

async function action(name, extra = {}) {
  if (busy) {
    if (name === 'source') pendingSource = extra.source;
    return;
  }
  busy = true;
  document.body.setAttribute('aria-busy', 'true');
  const pending = setTimeout(() => notice(state?.source === 'cd' ? 'Cd lezen…' : 'Even geduld…'), 700);
  try {
    const response = await fetch('/api/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CDSpeler': '1' },
      body: JSON.stringify({ action: name, ...extra })
    });
    const data = await response.json();
    if (!response.ok) throw Error(data.error || 'De opdracht is niet gelukt.');
    clearTimeout(pending);
    notice('');
    await poll(true);
  } catch (error) {
    if (name === 'source' && desiredSource === extra.source && pendingSource === null) desiredSource = null;
    notice(error.message);
  } finally {
    clearTimeout(pending);
    busy = false;
    document.body.removeAttribute('aria-busy');
    if (pendingSource !== null) {
      const next = pendingSource;
      pendingSource = null;
      if (state?.source !== next) await action('source', {source: next});
    }
  }
}

function setSource(source) {
  sourceRevision++;
  desiredSource = source;
  for (const item of ['cd', 'dvd', 'vinyl', 'spotify', 'plexamp']) {
    $('source-' + item).classList.toggle('selected', item === source);
    $('source-' + item).setAttribute('aria-pressed', String(item === source));
  }
  if (busy || state?.source !== source) action('source', { source });
  else desiredSource = null;
}
function togglePlay() {
  action(state?.player?.state === 'play' || state?.player?.buffering ? 'pause' : 'play');
}

$('seek').addEventListener('input', event => {
  const input = event.target;
  input.style.setProperty('--progress', (100 * Number(input.value) / Math.max(1, Number(input.max))) + '%');
  text('elapsed', duration(input.value));
});
$('seek').addEventListener('change', event => action('seek', { seconds: Number(event.target.value) }));
$('release-select').addEventListener('change', event => action('release', { release: event.target.value }));
$('cover').addEventListener('error', () => {
  show('cover', false);
  show('art-placeholder', true);
});

function poll(force = false) {
  if (polling) return force ? polling.then(() => poll(true)) : polling;
  polling = readStatus();
  return polling;
}

async function readStatus() {
  const revision = sourceRevision;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 12000);
  let connected = false;
  try {
    const response = await fetch('/api/status', { cache: 'no-store', signal: controller.signal });
    if (!response.ok) throw Error('Status niet beschikbaar');
    const incoming = await response.json();
    // A status requested before the click must never undo that click.
    if (revision !== sourceRevision || (desiredSource && incoming.source !== desiredSource)) return;
    state = incoming;
    if (desiredSource === incoming.source) desiredSource = null;
    lastStatusAt = Date.now();
    failed = 0;
    text('connection-label', 'Verbonden met de speler');
    $('connection').title = 'Verbonden met de speler';
    $('connection').className = 'connection online';
    connected = true;
  } catch (error) {
    failed++;
    text('connection-label', 'Geen verbinding met de speler');
    $('connection').title = 'Geen verbinding met de speler';
    $('connection').className = 'connection offline';
    if (failed > 2) notice('Geen verbinding met de speler. Opnieuw verbinden…');
  } finally {
    clearTimeout(timeout);
    polling = null;
  }
  if (connected) {
    try { render(); }
    catch (error) {
      console.error('Spelerweergave mislukt', error);
      notice('Verbonden met de speler. De weergave kon niet worden bijgewerkt; ververs de pagina.');
    }
  }
}

function renderProgress() {
  if (!state || document.activeElement === $('seek')) return;
  const p = state.player || {};
  const d = state.disc;
  const song = Math.max(0, (d?.tracks || []).findIndex(t => t.number === Number(p.track)));
  const total = Number(p.duration) || (state.source === 'cd' ? d.tracks[song]?.seconds : 0) || 0;
  const advance = p.state === 'play' && !p.buffering ? (Date.now() - lastStatusAt) / 1000 : 0;
  const elapsed = Math.min(total || Infinity, (Number(p.elapsed) || 0) + advance);
  $('seek').max = total || 1;
  $('seek').value = elapsed;
  $('seek').style.setProperty('--progress', (100 * elapsed / Math.max(1, total)) + '%');
  text('elapsed', duration(elapsed));
  text('duration', duration(total));
}

function render() {
  const speakerConnected = state.output?.speaker_connected ?? (state.output?.type === 'bluetooth' && state.output?.playing === true);
  const speakerLabel = speakerConnected ? 'Bluetooth: verbonden met IKEA VAPPEBY' : 'Bluetooth: IKEA VAPPEBY niet verbonden';
  $('speaker-connection').classList.toggle('connected', !!speakerConnected);
  $('speaker-connection').setAttribute('aria-label', speakerLabel);
  $('speaker-connection').title = speakerLabel;
  document.body.setAttribute('data-source', state.source);
  ensureQuietVinylRecognition();
  const isCD = state.source === 'cd';
  const isPlex = state.source === 'plexamp';
  // Verified server metadata may arrive after the initial local lookup missed.
  if (state.source === 'cd' && state.disc?.release && state.archive?.metadata?.release === state.disc.release) {
    state.disc.metadata_status = 'found';
    state.disc.cover ||= '/cover/' + state.disc.release + '-1200.jpg';
  }
  const isVinyl = state.source === 'vinyl';
  const isDVD = state.source === 'dvd';
  const serviceName = isPlex ? 'Plexamp' : 'Spotify';
  const d = state.disc;
  const p = state.player || {};
  const sp = (isPlex ? state.plexamp : state.spotify) || {};
  const song = Math.max(0, (d?.tracks || []).findIndex(t => t.number === Number(p.track)));
  const playing = p.state === 'play';
  const buffering = !!p.buffering;
  const playable = isVinyl ? false : isCD ? d.present : isPlex ? sp.connected && sp.has_track : !!sp.title && sp.logged_in;
  const saved = state.archive || {};
  show('archive-status', isCD && (!!d.present || !!saved.error));
  show('archive-retry', isCD && !!d.present && !!saved.blocked && !saved.drive_blocked);
  const activeRip = d.tracks.find(t => ['ripping','uploading','retrying_upload'].includes(t.storage));
  const discInfo = d.disc_total > 1 ? `CD ${d.disc_number} van ${d.disc_total} · ` : '';
  text('archive-status', saved.error || (saved.stored === saved.total && saved.total
    ? `${discInfo}Opgeslagen · ${saved.stored} nummers` + (saved.awaiting_metadata ? ' · wacht op albuminformatie voor Plex' : '')
    : `${discInfo}${p.playback_source === 'local' && playing ? 'Afspelen tijdens opslaan' : 'Automatisch opslaan'} · ${saved.stored || 0}/${saved.total || d.tracks.length}` +
      (activeRip ? ` · ${activeRip.storage === 'ripping' ? 'Uitlezen' : 'Uploaden'} ${activeRip.number}` : '')) +
      (saved.skipped ? ` · ${saved.skipped} overgeslagen` : '') + (saved.blocked ? ` · ${saved.blocked} nummers wachten op herstel` : ''));
  for (const source of ['cd', 'dvd', 'vinyl', 'spotify', 'plexamp']) {
    const selected = state.source === source;
    $('source-' + source).classList.toggle('selected', selected);
    $('source-' + source).setAttribute('aria-pressed', String(selected));
  }
  show('track-section', isCD);
  show('queue-section', isCD);
  renderQueue();
  show('spotify-connect', !isCD && !isPlex && !isVinyl && !isDVD);
  show('dvd-panel', isDVD);
  show('artist', !isDVD || !!state.dvd?.movie?.year);
  show('plexamp-connect', isPlex);
  show('playback-controls', !isVinyl && !isDVD);
  show('vinyl-panel', isVinyl);
  $('seek').closest('.progress').hidden = !playable;
  $('eject').disabled = !d.present;
  show('play-symbol', !playing && !buffering);
  show('pause-symbol', playing && !buffering);
  show('loading-symbol', buffering);
  $('play').setAttribute('aria-label', buffering ? 'Laden onderbreken' : playing ? 'Pauzeren' : 'Afspelen');
  $('play').setAttribute('aria-busy', String(buffering));
  $('play').disabled = !playable;
  $('seek').disabled = !playable || buffering;
  $('previous').disabled = !playable || (isCD ? !state.queue?.previous : !sp.available_actions?.skip_prev);
  $('next').disabled = !playable || (isCD ? !state.queue?.upcoming?.length && !state.queue?.shuffle : !sp.available_actions?.skip_next);
  if (isCD) {
    text('album-name', d.present ? d.title : 'CD');
    text('now-artist', d.tracks[song]?.artist || (d.artist !== 'Various Artists' ? d.artist : '') || '');
    text('track-title', d.present ? d.tracks[song]?.title || 'Audio-cd' : d.loading ? 'Cd lezen…' : 'Geen cd');
    text('artist', d.present ? (d.metadata_status === 'loading' ? 'Albuminformatie ophalen…' : d.artist || 'Onbekende artiest') : 'Plaats een audio-cd.');
    text('metadata-status', !d.present ? '' : d.metadata_status === 'retrying'
      ? 'Albuminformatie tijdelijk niet bereikbaar · opnieuw proberen…'
      : d.metadata_status === 'unknown' ? 'Geen albuminformatie gevonden'
      : d.metadata_status === 'choose' ? 'Meerdere albums passen · kies de juiste albumuitgave bij Alle nummers'
      : d.metadata_status === 'error' ? 'Albuminformatie kon niet worden verwerkt' : '');
    show('metadata-status', !!$('metadata-status').textContent);
    const totalSeconds = d.tracks.reduce((sum, track) => sum + track.seconds, 0);
    text('album-stats', d.present ? `${d.tracks.length} nummers · ${Math.round(totalSeconds / 60)} min` : '');
    const release = (d.releases || []).find(r => r.id === d.release);
    const year = release?.date?.match(/^\d{4}/)?.[0];
    const countries = {NL: 'Nederland', GB: 'Verenigd Koninkrijk', US: 'Verenigde Staten', DE: 'Duitsland', FR: 'Frankrijk', BE: 'België', JP: 'Japan', XE: 'Europa', XW: 'Wereldwijd'};
    const country = release?.country ? countries[release.country] || release.country : '';
    text('album-edition', d.present && (year || country) ? ['Uitgave' + (year ? ' ' + year : ''), country].filter(Boolean).join(' · ') : '');
    text('track-count', d.present ? d.tracks.length + ' nummers · ' + duration(d.tracks.reduce((sum, track) => sum + track.seconds, 0)) : '');
    renderTracks(d, song, p.state, buffering);
    const releases = d.releases || [];
    show('release-settings', releases.length > 1);
    const signature = JSON.stringify([releases.map(r => r.id), d.release]);
    if ($('release-select').dataset.signature !== signature) {
      $('release-select').dataset.signature = signature;
      const choices = releases.map(r => {
        const option = document.createElement('option');
        option.value = r.id;
        option.textContent = [r.title, r.country, r.date].filter(Boolean).join(' · ');
        option.selected = r.id === d.release;
        return option;
      });
      if (d.metadata_status === 'choose') {
        const placeholder = document.createElement('option');
        placeholder.value = ''; placeholder.textContent = 'Kies een albumuitgave';
        placeholder.disabled = true; placeholder.selected = true;
        choices.unshift(placeholder);
      }
      $('release-select').replaceChildren(...choices);
    }
  } else if (isVinyl) {
    renderVinyl();
  } else {
    text('metadata-status', '');
    show('metadata-status', false);
    text('album-stats', sp.album ? `Album: ${sp.album}` : '');
    text('album-edition', '');
    text('now-artist', sp.artist || '');
    text('album-name', sp.title || serviceName);
    text('track-title', sp.title || (isPlex ? playing ? 'Plexamp speelt' : 'Plexamp' : 'Spotify Connect'));
    text('artist', sp.artist || (isPlex && sp.metadata_loading ? 'Nummerinformatie ophalen…' : `Kies CDspeler in ${serviceName}.`));
    text('spotify-state', sp.title ? '' : sp.connected ? 'Kies CDspeler bij de apparaten in Spotify.' : 'Spotify verbinden…');
    text('plexamp-state', sp.connected ? sp.has_track ? '' : 'Gereed · kies CDspeler bij de afspeelapparaten in Plexamp.' : 'Plexamp verbinden…');
  }
  text('output-label', buffering ? (isCD ? 'Nummer voorbereiden…' : `${serviceName} laden…`) : (isCD ? 'CD · ' : `${serviceName} · `) + (state.output?.name || 'AUX'));
  if (isVinyl) text('output-label', state.vinyl?.monitor?.playing ? state.vinyl.monitor.name : 'Vinyl');
  if (isCD && p.pending_track) notice(`Nummer ${p.pending_track} voorbereiden. Het huidige nummer speelt door.`);
  if (isDVD) renderDVD();
  const nextCover = isDVD ? state.dvd?.movie?.cover || '' : isVinyl ? (state.vinyl?.state === 'matched' && !state.vinyl?.transition_pending ? state.vinyl?.track?.cover : '') : isCD ? d.cover : sp.cover;
  if ((nextCover || '') !== coverURL) {
    coverURL = nextCover || '';
    if (coverURL) {
      $('cover').src = coverURL;
      $('cover').alt = 'Albumcover van ' + (isDVD ? state.dvd?.movie?.title || state.dvd?.title || 'dvd' : isVinyl ? state.vinyl?.track?.title || 'vinyl' : isCD ? d.title : sp.album || sp.title);
    } else $('cover').removeAttribute('src');
    show('cover', !!coverURL);
    show('art-placeholder', !coverURL);
  }
  renderProgress();
  if (state.error) notice(state.error);
}


function renderVinyl() {
  const v = state.vinyl || {};
  const track = v.state === 'matched' && !v.transition_pending ? (v.track || {}) : {};
  document.body.classList.toggle('vinyl-unmatched', !track.title);
  text('album-name', track.title || 'Vinyl');
  text('artist', track.artist || 'Laat de plaat maar draaien.');
  text('track-title', track.title || 'Vinyl');
  text('now-artist', track.artist || '');
  text('album-stats', track.album || '');
  text('album-edition', '');
  text('metadata-status', '');
  show('metadata-status', false);
  show('vinyl-panel', !track.title);
}
function safeHTTPS(value) {
  try { const url = new URL(value); return url.protocol === 'https:' ? url.href : ''; }
  catch { return ''; }
}

function trackLabel(track, albumArtist) {
  const label = document.createElement('span'); label.className = 'track-label';
  const title = document.createElement('span'); title.className = 'track-name'; title.textContent = track.title;
  const artist = document.createElement('span'); artist.className = 'track-artist';
  artist.textContent = track.artist || (albumArtist !== 'Various Artists' ? albumArtist : '') || 'Onbekende artiest';
  label.append(title, artist);
  if (!track.ready) {
    const status = document.createElement('span'); status.className = 'track-storage';
    status.textContent = track.storage === 'skipped' ? 'Overgeslagen'
      : track.storage === 'ripping' ? `◌ Uitlezen · ${track.progress || 0}%`
      : track.storage === 'uploading' ? `↑ Uploaden · ${track.progress || 0}%`
      : track.storage === 'queued' ? 'Wacht op upload'
      : track.storage === 'processing' ? '◌ Gereedmaken op server'
      : track.storage === 'error' ? '↻ Opnieuw proberen' : 'Nog niet opgeslagen';
    if (track.playable) status.textContent += ' · afspeelbaar';
    label.append(status);
  }
  return label;
}

function renderTracks(disc, song, playerState, buffering = false) {
  const signature = JSON.stringify([disc.id, disc.tracks, song, playerState, buffering]);
  if (signature === lastTracks) return;
  lastTracks = signature;
  const rows = [];
  if (!disc.present) {
    const empty = document.createElement('p');
    empty.className = 'empty';
    empty.textContent = 'Geen cd geplaatst.';
    rows.push(empty);
  }
  for (const [i, track] of disc.tracks.entries()) {
    const row = document.createElement('button');
    const active = i === song && playerState !== 'stop';
    row.className = 'track-row' + (active ? ' active' : '') + (!track.ready ? ' not-ready' : '');
    row.disabled = track.storage === 'skipped';
    row.setAttribute('aria-label', (track.ready || track.playable ? 'Speel ' : 'Geef voorrang aan ') + track.title);
    if (active) row.setAttribute('aria-current', 'true');
    const number = document.createElement('span');
    number.className = 'number';
    number.textContent = active && playerState === 'play' && !buffering ? '▶' : String(track.number);
    const title = trackLabel(track, disc.artist);
    const time = document.createElement('span');
    time.className = 'time';
    time.textContent = duration(track.seconds);
    row.append(number, title, time);
    row.onclick = () => action('track', { track: track.number });
    rows.push(row);
  }
  $('track-list').replaceChildren(...rows);
}

let queueSignature = '';
function moveQueue(number, delta) {
  const tracks = [...(state.queue?.upcoming || [])];
  const from = tracks.indexOf(number), to = from + delta;
  if (from < 0 || to < 0 || to >= tracks.length) return;
  [tracks[from], tracks[to]] = [tracks[to], tracks[from]];
  action('queue-order', {tracks});
}
function renderQueue() {
  const q = state.queue || {};
  const tracks = state.disc?.tracks || [];
  const upcoming = q.upcoming || [];
  const signature = JSON.stringify([q, tracks, state.disc?.present]);
  if (signature === queueSignature) return;
  queueSignature = signature;
  $('shuffle').setAttribute('aria-pressed', String(!!q.shuffle));
  $('shuffle').disabled = !state.disc?.present;
  text('queue-count', state.disc?.present ? `Ronde ${q.round || 1} · ${upcoming.length} hierna` : 'Plaats een cd om te beginnen.');
  const rows = upcoming.map((number, index) => {
    const track = tracks.find(t => t.number === number);
    if (!track) return document.createElement('div');
    const row = document.createElement('div');
    row.className = 'queue-row' + (!track.ready ? ' not-ready' : '');
    const name = document.createElement('button');
    name.className = 'queue-track';
    const n = document.createElement('span'); n.className = 'number'; n.textContent = number;
    const title = trackLabel(track, state.disc?.artist);
    const time = document.createElement('span'); time.className = 'time'; time.textContent = duration(track.seconds);
    name.append(n, title, time);
    name.onclick = () => action('track', {track: number});
    row.append(name);
    for (const [symbol, label, fn, disabled] of [
      ['↑', 'Omhoog', () => moveQueue(number, -1), index === 0],
      ['↓', 'Omlaag', () => moveQueue(number, 1), index === upcoming.length - 1],
      ['×', 'Deze ronde overslaan', () => action('queue-skip', {track: number}), false]]) {
      const button = document.createElement('button');
      button.className = 'queue-edit'; button.textContent = symbol;
      button.setAttribute('aria-label', label + ': ' + track.title);
      button.title = label; button.disabled = disabled; button.onclick = fn;
      row.append(button);
    }
    return row;
  });
  if (!rows.length) {
    const empty = document.createElement('p'); empty.className = 'empty';
    empty.textContent = q.shuffle && q.current ? 'Na dit nummer begint een nieuwe shuffle-ronde.' : 'Geen nummers meer in de wachtrij.';
    rows.push(empty);
  }
  $('queue-list').replaceChildren(...rows);
}

poll();
setInterval(() => { if (!document.hidden) poll(); }, 1000);
setInterval(renderProgress, 500);
document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });

// TV remotes can move between visible controls with their arrow keys.
document.addEventListener('keydown', event => {
  if (!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)) return;
  if (['INPUT','SELECT','TEXTAREA'].includes(document.activeElement?.tagName)) return;
  const controls = [...document.querySelectorAll('button:not(:disabled),a[href],summary,input:not(:disabled),select:not(:disabled)')].filter(el => el.getClientRects().length);
  if (!controls.length) return;
  const current = document.activeElement;
  if (!controls.includes(current)) { controls[0].focus(); event.preventDefault(); return; }
  const r = current.getBoundingClientRect(); const x = r.x + r.width/2, y = r.y + r.height/2;
  const horizontal = ['ArrowLeft','ArrowRight'].includes(event.key), sign = ['ArrowRight','ArrowDown'].includes(event.key) ? 1 : -1;
  const choices = controls.filter(el => el !== current).map(el => {
    const a = el.getBoundingClientRect(), dx = a.x+a.width/2-x, dy = a.y+a.height/2-y;
    return {el, forward:(horizontal ? dx : dy)*sign, side:Math.abs(horizontal ? dy : dx)};
  }).filter(a => a.forward > 5).sort((a,b) => (a.forward+a.side*3)-(b.forward+b.side*3));
  if (choices.length) { event.preventDefault(); choices[0].el.focus(); }
});

let vinylAutoRequested = false;
function ensureQuietVinylRecognition() {
  if (state.source !== 'vinyl') { vinylAutoRequested = false; return; }
  if (state.vinyl?.automatic || vinylAutoRequested || !state.vinyl?.connected || !state.vinyl?.available) return;
  vinylAutoRequested = true;
  fetch('/api/action', {method:'POST',headers:{'Content-Type':'application/json','X-CDSpeler':'1'},body:JSON.stringify({action:'vinyl-auto',enabled:true})})
    .catch(error => console.warn('Automatische herkenning niet bereikbaar', error));
}

function renderDVD() {
  const d = state.dvd || {};
  const labels = {checking:'DVD controleren…',absent:'Plaats een dvd in de drive.',detected:'',streaming:'Stream actief',ejecting:'DVD uitwerpen…'};
  const movie=d.movie || {};
  text('album-name', movie.title || d.title || 'DVD');text('artist',movie.year || '');
  text('dvd-cast',movie.cast ? 'Met '+movie.cast : '');show('dvd-cast',!!movie.cast);
  show('dvd-imdb',!!movie.url);
  if (movie.url) $('dvd-imdb').setAttribute('href',movie.url);
  text('album-stats','');text('album-edition','');show('metadata-status',false);
  text('track-title','');text('now-artist','');text('output-label','');
  const message=d.error || labels[d.state] || '';text('dvd-status',message);show('dvd-status',!!message);
  const minutes=Math.floor((Number(d.seconds)||0)/60), seconds=Math.floor((Number(d.seconds)||0)%60);
  text('dvd-duration',d.seconds ? (minutes>=60 ? Math.floor(minutes/60)+' u '+String(minutes%60).padStart(2,'0')+' min' : minutes+' min '+seconds+' sec') : '—');
  text('dvd-subtitles',d.present ? d.dutch_subtitles ? 'Nederlands · automatisch' : 'Geen Nederlands beschikbaar' : '—');
  text('dvd-audio',(d.audio_languages || []).join(' · ') || '—');
  text('dvd-video',[d.width && d.height ? d.width+' × '+d.height : '',d.aspect].filter(Boolean).join(' · ') || '—');
  $('dvd-eject').disabled=!d.present || d.state==='ejecting';
  show('dvd-stop',!!d.streaming);
}
