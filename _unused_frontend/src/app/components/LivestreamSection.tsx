'use client';

import { useEffect, useState } from 'react';
import { API, Channel, UploadItem, ProductionJob, Pipeline, LiveJob, fmt, fmtBytes, statusColor } from '../types';

const inputStyle: React.CSSProperties = {
  width: '100%', padding: '10px 14px', fontSize: 13,
  background: 'rgba(255,255,255,.05)', border: '1px solid rgba(255,255,255,.08)',
  borderRadius: 10, color: '#fff', outline: 'none',
};

const s = {
  card: { background: '#101828', border: '1px solid rgba(255,255,255,.06)', borderRadius: 16, padding: 20 },
  btn: { padding: '10px 20px', borderRadius: 10, border: 'none', background: 'linear-gradient(135deg,#00539C,#003a6e)', color: '#fff', fontWeight: 700, fontSize: 13, cursor: 'pointer' },
  badge: (color: string) => ({ fontSize: 10, fontWeight: 700, padding: '3px 8px', borderRadius: 6, background: color + '20', color }),
  table: { width: '100%', borderCollapse: 'collapse' as const },
  th: { padding: '10px 12px', textAlign: 'left' as const, fontSize: 10, fontWeight: 700, color: '#64748b', textTransform: 'uppercase' as const, borderBottom: '1px solid rgba(255,255,255,.06)' },
  td: { padding: '10px 12px', borderBottom: '1px solid rgba(255,255,255,.04)', fontSize: 13 },
  empty: { textAlign: 'center' as const, padding: 40, color: '#64748b' },
};

export default function LivestreamSection({ channels, lives, activeChannelId, onReload }: { channels: Channel[]; lives: LiveJob[]; activeChannelId: number | null; onReload: () => void }) {
  const [form, setForm] = useState({ title: "", video_source: "", duration_hours: 12, quality: "low", visibility: "unlisted", scheduled_at: "", use_mp3: true, use_sfx: true });
  const [submitting, setSubmitting] = useState(false);
  const [streamKey, setStreamKey] = useState("");

  const activeChannel = channels.find(c => c.id === activeChannelId);

  const createJob = async () => {
    if (!activeChannelId) return alert("Pilih channel dulu");
    setSubmitting(true);
    try {
      const resp = await fetch(`${API}/livestream`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ channel_id: activeChannelId, ...form }),
      });
      const data = await resp.json();
      if (data.success) {
        onReload();
        setForm({ ...form, title: "", video_source: "" });
      } else {
        alert(data.detail || "Gagal membuat livestream");
      }
    } catch { alert("Error"); }
    setSubmitting(false);
  };

  const stopJob = async (id: number) => {
    if (!confirm("Stop livestream ini?")) return;
    await fetch(`${API}/livestream/${id}/stop`, { method: "POST" });
    onReload();
  };

  const deleteJob = async (id: number) => {
    if (!confirm("Hapus job ini?")) return;
    await fetch(`${API}/livestream/${id}`, { method: "DELETE" });
    onReload();
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* Channel Status */}
      {activeChannel && (
        <div style={{ display: "flex", gap: 12, padding: 12, background: "rgba(255,255,255,.03)", border: "1px solid rgba(255,255,255,.06)", borderRadius: 12 }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: activeChannel.stream_key ? "#10b981" : "#ef4444" }}>
            🔑 Stream Key: {activeChannel.stream_key ? "OK" : "NOT SET"}
          </span>
        </div>
      )}

      {/* Create Form */}
      <div style={{ ...s.card }}>
        <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 16 }}>🔴 Create Livestream</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <div>
            <label style={labelStyle}>Title</label>
            <input value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} placeholder="Livestream title" style={inputStyle} />
          </div>
          <div>
            <label style={labelStyle}>Video Source</label>
            <input value={form.video_source} onChange={e => setForm({ ...form, video_source: e.target.value })} placeholder="video.mp4 (kosongkan untuk auto)" style={inputStyle} />
          </div>
          <div>
            <label style={labelStyle}>Duration (hours)</label>
            <input type="number" value={form.duration_hours} onChange={e => setForm({ ...form, duration_hours: +e.target.value })} style={inputStyle} />
          </div>
          <div>
            <label style={labelStyle}>Quality</label>
            <select value={form.quality} onChange={e => setForm({ ...form, quality: e.target.value })} style={inputStyle}>
              <option value="low">Low (720p)</option>
              <option value="high">High (1080p)</option>
            </select>
          </div>
          <div>
            <label style={labelStyle}>Visibility</label>
            <select value={form.visibility} onChange={e => setForm({ ...form, visibility: e.target.value })} style={inputStyle}>
              <option value="unlisted">Unlisted</option>
              <option value="public">Public</option>
              <option value="private">Private</option>
              <option value="scheduled">Scheduled</option>
            </select>
            {form.visibility === "scheduled" && (
              <div style={{ marginTop: 8 }}>
                <label style={labelStyle}>Schedule At</label>
                <input
                  type="datetime-local"
                  value={form.scheduled_at}
                  onChange={e => setForm({ ...form, scheduled_at: e.target.value })}
                  style={inputStyle}
                />
              </div>
            )}
          </div>
          <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, cursor: "pointer" }}>
              <input type="checkbox" checked={form.use_mp3} onChange={e => setForm({ ...form, use_mp3: e.target.checked })} /> MP3
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, cursor: "pointer" }}>
              <input type="checkbox" checked={form.use_sfx} onChange={e => setForm({ ...form, use_sfx: e.target.checked })} /> SFX
            </label>
          </div>
        </div>
        <button onClick={createJob} disabled={submitting || !activeChannelId} style={{ marginTop: 16, ...s.btn, opacity: submitting ? .6 : 1 }}>
          {submitting ? "⏳ ..." : "🔴 Start Livestream"}
        </button>
      </div>

      {/* Stream Key Manager */}
      <div style={{ ...s.card }}>
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12 }}>🔑 Stream Key Manager</div>
        {/* Current key display */}
        {activeChannel?.stream_key && (
          <div style={{ marginBottom: 12, padding: "10px 14px", background: "rgba(16,185,129,.08)", border: "1px solid rgba(16,185,129,.2)", borderRadius: 10, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, color: "#64748b", textTransform: "uppercase" as const }}>Key Saat Ini</div>
              <div style={{ fontSize: 13, fontWeight: 700, color: "#10b981", fontFamily: "monospace", marginTop: 4 }}>
                {activeChannel.stream_key.substring(0, 8)}****{activeChannel.stream_key.substring(activeChannel.stream_key.length - 4)}
              </div>
            </div>
            <span style={{ fontSize: 10, fontWeight: 700, color: "#10b981" }}>✅ Aktif</span>
          </div>
        )}
        <div style={{ display: "flex", gap: 8 }}>
          <input value={streamKey} onChange={e => setStreamKey(e.target.value)} placeholder={activeChannel?.stream_key ? "Masukkan key baru untuk mengganti..." : "Stream key dari YouTube Studio"} style={{ ...inputStyle, flex: 1 }} />
          <button onClick={async () => {
            if (!activeChannelId || !streamKey) return;
            if (activeChannel?.stream_key) {
              if (!confirm(`Key lama akan diganti dengan key baru. Lanjutkan?`)) return;
            }
            await fetch(`${API}/channels/${activeChannelId}`, {
              method: "PUT", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ stream_key: streamKey }),
            });
            setStreamKey("");
            onReload();
            alert("✅ Stream key berhasil disimpan!");
          }} style={s.btn}>💾 Save</button>
        </div>
      </div>

      {/* Jobs Table */}
      <div style={{ ...s.card, padding: 0, overflow: "hidden" }}>
        <div style={{ padding: "16px 20px", borderBottom: "1px solid rgba(255,255,255,.06)", fontSize: 14, fontWeight: 700 }}>🔴 Livestream Jobs ({lives.length})</div>
        <table style={s.table}>
          <thead><tr>{["ID", "Title", "Status", "Duration", "Quality", "PID", "Created", "Actions"].map(h => <th key={h} style={s.th}>{h}</th>)}</tr></thead>
          <tbody>
            {lives.map(l => <tr key={l.id}>
              <td style={s.td}>#{l.id}</td>
              <td style={{ ...s.td, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{l.title || "-"}</td>
              <td style={s.td}><span style={s.badge(statusColor[l.status])}>{l.status}</span></td>
              <td style={s.td}>{l.duration_hours}h</td>
              <td style={s.td}>{l.quality}</td>
              <td style={{ ...s.td, fontFamily: "monospace", color: "#94a3b8" }}>{l.process_id || "-"}</td>
              <td style={{ ...s.td, fontSize: 12, color: "#64748b" }}>{new Date(l.created_at).toLocaleDateString("id-ID")}</td>
              <td style={s.td}>
                <div style={{ display: "flex", gap: 4 }}>
                  {l.status === "running" && <button onClick={() => stopJob(l.id)} style={{ fontSize: 10, padding: "3px 8px", borderRadius: 6, border: "1px solid rgba(239,68,68,.2)", background: "rgba(239,68,68,.08)", color: "#ef4444", cursor: "pointer" }}>⏹ Stop</button>}
                  {l.status !== "running" && <button onClick={() => deleteJob(l.id)} style={{ fontSize: 10, padding: "3px 8px", borderRadius: 6, border: "1px solid rgba(255,255,255,.06)", background: "transparent", color: "#64748b", cursor: "pointer" }}>🗑️</button>}
                </div>
              </td>
            </tr>)}
            {lives.length === 0 && <tr><td colSpan={8} style={{ ...s.td, textAlign: "center", padding: 40, color: "#64748b" }}>Belum ada livestream</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Monitor Livestream Section ──────────────────────────────────

