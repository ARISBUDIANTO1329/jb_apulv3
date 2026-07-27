// ── API Helper ──────────────────────────────────────────────────

async function api(path, options = {}) {
  const resp = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  return resp.json();
}

// ── State ───────────────────────────────────────────────────────

let channels = [];
let activeChannelId = null;

// ── Channel Management ──────────────────────────────────────────

async function loadChannels() {
  channels = await api('/channels');
  renderChannelSelector();
  document.getElementById('channel-count').textContent = channels.length;
  return channels;
}

function renderChannelSelector() {
  const sel = document.getElementById('active-channel');
  if (!sel) return;
  sel.innerHTML = '<option value="">Semua Channel</option>';
  channels.forEach(ch => {
    sel.innerHTML += `<option value="${ch.id}" ${activeChannelId == ch.id ? 'selected' : ''}>#${ch.id} — ${ch.name}</option>`;
  });
}

function setActiveChannel(id) {
  activeChannelId = id ? Number(id) : null;
  localStorage.setItem('jb_active_channel', id);
  if (typeof onChannelChange === 'function') onChannelChange();
}

function showAddChannel() {
  document.getElementById('modal-add').classList.remove('hidden');
}

function hideAddChannel() {
  document.getElementById('modal-add').classList.add('hidden');
}

async function addChannel() {
  const name = document.getElementById('new-channel-name').value.trim();
  if (!name) return alert('Nama channel wajib diisi');
  await api('/channels', {
    method: 'POST',
    body: JSON.stringify({
      name,
      niche: document.getElementById('new-channel-niche').value,
      youtube_channel_id: document.getElementById('new-channel-youtube-id').value || null,
    }),
  });
  hideAddChannel();
  document.getElementById('new-channel-name').value = '';
  document.getElementById('new-channel-niche').value = '';
  document.getElementById('new-channel-youtube-id').value = '';
  await loadChannels();
  if (typeof onChannelChange === 'function') onChannelChange();
}

async function deleteChannel(id) {
  if (!confirm('Hapus channel dan semua data terkait?')) return;
  await api(`/channels/${id}`, { method: 'DELETE' });
  await loadChannels();
  if (typeof onChannelChange === 'function') onChannelChange();
}

// ── Utilities ───────────────────────────────────────────────────

const fmt = n => n >= 1e6 ? (n/1e6).toFixed(1)+'M' : n >= 1e3 ? (n/1e3).toFixed(1)+'K' : String(n);
const fmtBytes = b => {
  if (b <= 0) return '0 B';
  const u = ['B','KB','MB','GB','TB'];
  const i = Math.min(Math.floor(Math.log(b)/Math.log(1024)), u.length-1);
  return (b/Math.pow(1024,i)).toFixed(i===0?0:1)+' '+u[i];
};

function badge(status) {
  return `<span class="badge badge-${status}">${status}</span>`;
}

function progressBar(value, color = 'blue') {
  return `<div class="progress-bar"><div class="progress-fill progress-${color}" style="width:${value}%"></div></div>`;
}

function confirmAction(msg, fn) {
  if (confirm(msg)) fn();
}

// ── Init ────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
  activeChannelId = localStorage.getItem('jb_active_channel') || null;
  await loadChannels();
});

// Close modal on outside click
document.addEventListener('click', e => {
  if (e.target.classList.contains('modal')) {
    e.target.classList.add('hidden');
  }
});
