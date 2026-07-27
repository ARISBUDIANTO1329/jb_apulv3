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

export default function MediaSection({ channelId, channels }: { channelId: number | null; channels: Channel[] }) {
  const [activeGroup, setActiveGroup] = useState("video-raw");
  const [files, setFiles] = useState<{ filename: string; path: string; size: number; size_mb: number }[]>([]);
  const [stats, setStats] = useState<Record<string, { count: number; size_mb: number }>>({});
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [search, setSearch] = useState("");
  const [uploadGroup, setUploadGroup] = useState("video-raw");

  useEffect(() => {
    if (!channelId) { setFiles([]); setStats({}); return; }
    setLoading(true);
    fetch(`${API}/media/files?channel_id=${channelId}&asset_type=${activeGroup}`)
      .then(r => r.json())
      .then(data => { setFiles(data.files || []); setLoading(false); })
      .catch(() => setLoading(false));
    fetch(`${API}/channels/${channelId}/storage`)
      .then(r => r.json())
      .then(data => setStats(data.stats || {}))
      .catch(() => {});
  }, [channelId, activeGroup]);

  const handleUpload = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    const fileInput = form.querySelector('input[type="file"]') as HTMLInputElement;
    const file = fileInput?.files?.[0];
    if (!file || !channelId) return;
    setUploading(true);
    const formData = new FormData();
    formData.append("channel_id", String(channelId));
    formData.append("asset_type", uploadGroup);
    formData.append("file", file);
    try {
      await fetch(`${API}/media/upload`, { method: "POST", body: formData });
      const resp = await fetch(`${API}/media/files?channel_id=${channelId}&asset_type=${activeGroup}`);
      const data = await resp.json();
      setFiles(data.files || []);
      const statsResp = await fetch(`${API}/channels/${channelId}/storage`);
      const statsData = await statsResp.json();
      setStats(statsData.stats || {});
      fileInput.value = "";
    } catch {}
    setUploading(false);
  };

  const handleDelete = async (filename: string) => {
    if (!confirm(`Hapus ${filename}?`)) return;
    const resp = await fetch(`${API}/media?channel_id=${channelId}&asset_type=${activeGroup}`);
    const items = await resp.json();
    const item = items.find((i: { filename: string }) => i.filename === filename);
    if (item) {
      await fetch(`${API}/media/${item.id}`, { method: "DELETE" });
      setFiles(files.filter(f => f.filename !== filename));
    }
  };

  const filteredFiles = search ? files.filter(f => f.filename.toLowerCase().includes(search.toLowerCase())) : files;
  const activeGroupData = MEDIA_GROUPS.find(g => g.key === activeGroup);
  const totalChannelSize = Object.values(stats).reduce((s, g) => s + (g.size_mb || 0), 0);
  const activeChannel = channels.find(c => c.id === channelId);

  if (!channelId) {
    return (
      <div style={{ padding: 16, borderRadius: 10, background: "rgba(239,68,68,.08)", border: "1px solid rgba(239,68,68,.2)", color: "#ef4444", fontSize: 14 }}>
        Pilih channel aktif terlebih dahulu dari dropdown di atas.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* Storage Info */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <div style={{ background: "rgba(255,255,255,.04)", border: "1px solid rgba(255,255,255,.08)", borderRadius: 16, padding: 24 }}>
          <div style={{ fontSize: 19, fontWeight: 700 }}>Channel Asset Usage</div>
          <div style={{ color: "#64748b", fontSize: 14, marginTop: 6 }}>Ringkasan aset channel aktif</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 24 }}>
            <div style={{ background: "rgba(255,255,255,.06)", border: "1px solid rgba(255,255,255,.08)", borderRadius: 10, padding: 18 }}>
              <div style={{ fontSize: 11, color: "#64748b" }}>Channel</div>
              <div style={{ fontSize: 18, fontWeight: 700, marginTop: 8 }}>{activeChannel?.name || "-"}</div>
              <div style={{ fontSize: 11, color: "#64748b", fontFamily: "monospace", marginTop: 4 }}>#{activeChannel?.id || ""}</div>
            </div>
            <div style={{ background: "rgba(255,255,255,.06)", border: "1px solid rgba(255,255,255,.08)", borderRadius: 10, padding: 18 }}>
              <div style={{ fontSize: 11, color: "#64748b" }}>Total Size</div>
              <div style={{ fontSize: 22, fontWeight: 800, marginTop: 6 }}>{fmtBytes(totalChannelSize * 1024 * 1024)}</div>
            </div>
          </div>
        </div>
        <div style={{ background: "rgba(255,255,255,.04)", border: "1px solid rgba(255,255,255,.08)", borderRadius: 16, padding: 24 }}>
          <div style={{ fontSize: 19, fontWeight: 700 }}>Storage Per Grup</div>
          <div style={{ color: "#64748b", fontSize: 14, marginTop: 6 }}>Kapasitas per tipe aset</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 12, marginTop: 16 }}>
            {MEDIA_GROUPS.slice(0, 6).map(g => (
              <div key={g.key} style={{ background: "rgba(255,255,255,.06)", border: "1px solid rgba(255,255,255,.08)", borderRadius: 8, padding: 12 }}>
                <div style={{ fontSize: 10, color: "#64748b", fontWeight: 700 }}>{g.icon} {g.label}</div>
                <div style={{ fontSize: 14, fontWeight: 700, marginTop: 4 }}>{stats[g.key]?.count || 0} file</div>
                <div style={{ fontSize: 10, color: "#64748b" }}>{fmtBytes((stats[g.key]?.size_mb || 0) * 1024 * 1024)}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Group Cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: 16 }}>
        {MEDIA_GROUPS.map(g => (
          <div
            key={g.key}
            onClick={() => setActiveGroup(g.key)}
            style={{
              background: activeGroup === g.key ? "rgba(96,165,250,.16)" : "rgba(255,255,255,.06)",
              border: activeGroup === g.key ? "1px solid rgba(96,165,250,.45)" : "1px solid rgba(255,255,255,.08)",
              borderRadius: 12, padding: "18px 16px", cursor: "pointer", minHeight: 112, transition: "all .3s",
              boxShadow: activeGroup === g.key ? "0 0 20px rgba(96,165,250,.1)" : "none",
            }}
          >
            <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 6 }}>{g.label}</div>
            <div style={{ fontSize: 13, color: "#64748b", lineHeight: 1.5 }}>{g.desc}</div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginTop: 16 }}>
              <div>
                <div style={{ fontSize: 26, fontWeight: 800, lineHeight: 1 }}>{stats[g.key]?.count || 0}</div>
                <div style={{ fontSize: 11, color: "#64748b" }}>files</div>
              </div>
              <span style={{ padding: "6px 14px", background: "rgba(255,255,255,.07)", border: "1px solid rgba(255,255,255,.08)", borderRadius: 9999, fontSize: 12, fontWeight: 700, color: "#94a3b8" }}>Open</span>
            </div>
          </div>
        ))}
      </div>

      {/* Upload Section */}
      <div style={{ background: "rgba(255,255,255,.04)", border: "1px solid rgba(255,255,255,.08)", borderRadius: 16, padding: 24 }}>
        <div style={{ fontSize: 19, fontWeight: 700 }}>Upload Asset</div>
        <div style={{ color: "#64748b", fontSize: 14, marginTop: 6 }}>Upload file ke folder channel aktif</div>
        <form onSubmit={handleUpload} style={{ marginTop: 18 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
            <div>
              <label style={{ display: "block", marginBottom: 8, fontSize: 11, fontWeight: 700, letterSpacing: 1, color: "#64748b", textTransform: "uppercase" as const }}>Target Folder</label>
              <select value={uploadGroup} onChange={e => setUploadGroup(e.target.value)} style={{ width: "100%", padding: "14px 18px", background: "#101a2b", border: "1px solid rgba(255,255,255,.08)", borderRadius: 10, color: "#f8fafc", fontSize: 14, fontWeight: 700, outline: "none" }}>
                {MEDIA_GROUPS.map(g => <option key={g.key} value={g.key} style={{ background: "#0b1220" }}>{g.label}</option>)}
              </select>
            </div>
            <div>
              <label style={{ display: "block", marginBottom: 8, fontSize: 11, fontWeight: 700, letterSpacing: 1, color: "#64748b", textTransform: "uppercase" as const }}>File</label>
              <input type="file" required accept="video/*,audio/*,image/*,.mp4,.mp3,.wav,.jpg,.jpeg,.png,.webp" style={{ width: "100%", padding: "14px 18px", background: "rgba(255,255,255,.06)", border: "1px solid rgba(255,255,255,.08)", borderRadius: 10, color: "#fff", fontSize: 14 }} />
            </div>
          </div>
          <button type="submit" disabled={uploading} style={{ marginTop: 16, padding: "12px 24px", borderRadius: 10, border: "none", background: "linear-gradient(135deg,#00539C,#003a6e)", color: "#FFD662", fontWeight: 700, fontSize: 14, cursor: "pointer", opacity: uploading ? .6 : 1 }}>
            {uploading ? "⏳ Uploading..." : "📤 Upload"}
          </button>
        </form>
      </div>

      {/* File Table */}
      <div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <div>
            <h2 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>{activeGroupData?.icon} {activeGroupData?.label}</h2>
            <p style={{ fontSize: 12, color: "#64748b", marginTop: 4 }}>{activeGroupData?.desc}</p>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span style={{ fontSize: 12, color: "#64748b" }}>{files.length} file</span>
            <span style={{ fontSize: 12, color: "#64748b" }}>•</span>
            <span style={{ fontSize: 12, color: "#64748b" }}>{fmtBytes(files.reduce((s, f) => s + f.size, 0))}</span>
          </div>
        </div>
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Cari file..." style={{ width: "100%", padding: "10px 14px", fontSize: 13, background: "rgba(255,255,255,.04)", border: "1px solid rgba(255,255,255,.08)", borderRadius: 10, color: "#fff", outline: "none", marginBottom: 16 }} />
        {loading ? (
          <div style={{ color: "#64748b", padding: 40, textAlign: "center" }}>Loading...</div>
        ) : filteredFiles.length === 0 ? (
          <div style={{ padding: 60, textAlign: "center", background: "rgba(255,255,255,.04)", border: "2px dashed rgba(255,255,255,.12)", borderRadius: 16, color: "#64748b", fontSize: 15 }}>
            {search ? "Tidak ada file yang cocok" : "Belum ada file di grup ini"}
          </div>
        ) : (
          <div style={{ background: "rgba(255,255,255,.04)", border: "1px solid rgba(255,255,255,.08)", borderRadius: 12, overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  {["Filename", "Size", "Actions"].map(h => (
                    <th key={h} style={{ background: "rgba(255,255,255,.05)", padding: "16px 20px", textAlign: "left", fontSize: 11, fontWeight: 700, letterSpacing: 1, color: "#64748b", textTransform: "uppercase" as const }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredFiles.map(f => (
                  <tr key={f.filename}>
                    <td style={{ padding: "14px 16px", borderTop: "1px solid rgba(255,255,255,.08)" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <span style={{ fontSize: 16 }}>{f.filename.match(/\.(mp4|mkv|avi|mov)$/i) ? "🎥" : f.filename.match(/\.(mp3|wav)$/i) ? "🎵" : f.filename.match(/\.(jpg|jpeg|png|webp)$/i) ? "🖼️" : "📄"}</span>
                        <div style={{ fontWeight: 700, color: "#e0e8f0" }}>{f.filename}</div>
                      </div>
                    </td>
                    <td style={{ padding: "14px 16px", borderTop: "1px solid rgba(255,255,255,.08)", color: "#94a3b8" }}>{fmtBytes(f.size)}</td>
                    <td style={{ padding: "14px 16px", borderTop: "1px solid rgba(255,255,255,.08)" }}>
                      <button onClick={() => handleDelete(f.filename)} style={{ fontSize: 11, padding: "6px 14px", borderRadius: 6, border: "1px solid rgba(239,68,68,.2)", background: "rgba(239,68,68,.08)", color: "#ef4444", cursor: "pointer", fontWeight: 700 }}>🗑️ Hapus</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

