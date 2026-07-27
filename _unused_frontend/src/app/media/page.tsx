"use client";

import { useEffect, useState } from "react";

const API = "http://localhost:8001";

interface Channel { id: number; name: string; }
interface MediaFile { filename: string; path: string; size: number; size_mb: number; }
interface StorageStats { [key: string]: { count: number; size_mb: number }; }

const GROUPS = [
  { key: "video", label: "Video", desc: "Footage video utama", icon: "🎬" },
  { key: "video-raw", label: "Video Raw", desc: "Video mentah sebelum proses seamless", icon: "🎥" },
  { key: "video-live", label: "Video Live", desc: "Footage hasil live", icon: "📹" },
  { key: "livestream-ready", label: "Livestream Ready", desc: "Video siap untuk livestream", icon: "🔴" },
  { key: "upload_ready", label: "Upload Ready", desc: "Video final siap upload YouTube", icon: "📤" },
  { key: "mp3", label: "MP3", desc: "Audio / musik / voice", icon: "🎵" },
  { key: "sfx", label: "SFX", desc: "Efek suara pendek", icon: "🔊" },
  { key: "intro", label: "Intro", desc: "Video pembuka", icon: "🎬" },
  { key: "thumbnail", label: "Thumbnail", desc: "Gambar thumbnail", icon: "🖼️" },
  { key: "metadata", label: "Metadata", desc: "File metadata pendukung", icon: "📝" },
];

const fmtBytes = (b: number) => {
  if (b <= 0) return "0 B";
  const u = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(Math.floor(Math.log(b) / Math.log(1024)), u.length - 1);
  return (b / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1) + " " + u[i];
};

export default function MediaPage() {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [activeChannelId, setActiveChannelId] = useState<number | null>(null);
  const [activeGroup, setActiveGroup] = useState("video-raw");
  const [files, setFiles] = useState<MediaFile[]>([]);
  const [stats, setStats] = useState<StorageStats>({});
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [search, setSearch] = useState("");
  const [uploadGroup, setUploadGroup] = useState("video-raw");

  useEffect(() => {
    fetch(`${API}/api/channels`).then(r => r.json()).then(setChannels);
  }, []);

  useEffect(() => {
    if (!activeChannelId) { setFiles([]); setStats({}); return; }
    setLoading(true);
    // Load files for active group
    fetch(`${API}/api/media/files?channel_id=${activeChannelId}&asset_type=${activeGroup}`)
      .then(r => r.json())
      .then(data => { setFiles(data.files || []); setLoading(false); })
      .catch(() => setLoading(false));
    // Load storage stats
    fetch(`${API}/api/channels/${activeChannelId}/storage`)
      .then(r => r.json())
      .then(data => setStats(data.stats || {}))
      .catch(() => {});
  }, [activeChannelId, activeGroup]);

  const handleUpload = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    const fileInput = form.querySelector('input[type="file"]') as HTMLInputElement;
    const file = fileInput?.files?.[0];
    if (!file || !activeChannelId) return;
    setUploading(true);
    const formData = new FormData();
    formData.append("channel_id", String(activeChannelId));
    formData.append("asset_type", uploadGroup);
    formData.append("file", file);
    try {
      await fetch(`${API}/api/media/upload`, { method: "POST", body: formData });
      // Reload
      const resp = await fetch(`${API}/api/media/files?channel_id=${activeChannelId}&asset_type=${activeGroup}`);
      const data = await resp.json();
      setFiles(data.files || []);
      const statsResp = await fetch(`${API}/api/channels/${activeChannelId}/storage`);
      const statsData = await statsResp.json();
      setStats(statsData.stats || {});
      fileInput.value = "";
    } catch { }
    setUploading(false);
  };

  const handleDelete = async (filename: string) => {
    if (!confirm(`Hapus ${filename}?`)) return;
    const resp = await fetch(`${API}/api/media?channel_id=${activeChannelId}&asset_type=${activeGroup}`);
    const items = await resp.json();
    const item = items.find((i: { filename: string }) => i.filename === filename);
    if (item) {
      await fetch(`${API}/api/media/${item.id}`, { method: "DELETE" });
      setFiles(files.filter(f => f.filename !== filename));
    }
  };

  const filteredFiles = search ? files.filter(f => f.filename.toLowerCase().includes(search.toLowerCase())) : files;
  const activeChannel = channels.find(c => c.id === activeChannelId);
  const activeGroupData = GROUPS.find(g => g.key === activeGroup);
  const totalChannelSize = Object.values(stats).reduce((s, g) => s + (g.size_mb || 0), 0);

  return (
    <div style={{ minHeight: "100vh", background: "#0a0e18", color: "#e0e8f0", fontFamily: "Inter,-apple-system,sans-serif" }}>
      <div style={{ padding: "24px 32px", display: "flex", flexDirection: "column", gap: 20 }}>

        {/* Header */}
        <div>
          <h1 style={{ fontSize: 32, fontWeight: 800, letterSpacing: "-.05em", margin: 0 }}>Asset Library</h1>
          <p style={{ color: "#64748b", fontSize: 15, marginTop: 8, maxWidth: 820, lineHeight: 1.6 }}>
            Penyimpanan aset berbasis channel aktif. Semua file diorganisir per folder sesuai tipe untuk memudahkan produksi konten.
          </p>
          <div style={{ display: "flex", gap: 10, marginTop: 12, flexWrap: "wrap" }}>
            <span style={{ padding: "6px 14px", background: "rgba(255,255,255,.07)", border: "1px solid rgba(255,255,255,.08)", borderRadius: 9999, fontSize: 12, fontWeight: 700, color: "#94a3b8" }}>
              <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: 50, background: activeChannel ? "#10b981" : "#ef4444", marginRight: 6 }}></span>
              Channel: {activeChannel?.name || "Belum dipilih"}
            </span>
            <span style={{ padding: "6px 14px", background: "rgba(255,255,255,.07)", border: "1px solid rgba(255,255,255,.08)", borderRadius: 9999, fontSize: 12, fontWeight: 700, color: "#94a3b8" }}>
              ID: {activeChannelId || "-"}
            </span>
            <span style={{ padding: "6px 14px", background: "rgba(255,255,255,.07)", border: "1px solid rgba(255,255,255,.08)", borderRadius: 9999, fontSize: 12, fontWeight: 700, color: "#94a3b8" }}>
              Folder: {activeGroupData?.label || "-"}
            </span>
            {/* Channel Selector */}
            <select
              value={activeChannelId || ""}
              onChange={e => setActiveChannelId(e.target.value ? Number(e.target.value) : null)}
              style={{ padding: "6px 14px", background: "rgba(255,255,255,.06)", border: "1px solid rgba(255,255,255,.08)", borderRadius: 9999, fontSize: 12, fontWeight: 700, color: "#fff", outline: "none", cursor: "pointer" }}
            >
              <option value="" style={{ background: "#0e1424" }}>Pilih Channel</option>
              {channels.map(ch => <option key={ch.id} value={ch.id} style={{ background: "#0e1424" }}>{ch.name}</option>)}
            </select>
          </div>
        </div>

        {!activeChannelId ? (
          <div style={{ padding: 16, borderRadius: 10, background: "rgba(239,68,68,.08)", border: "1px solid rgba(239,68,68,.2)", color: "#ef4444", fontSize: 14 }}>
            Pilih channel aktif terlebih dahulu sebelum membuka Asset Library.
          </div>
        ) : (
          <>
            {/* Storage Info */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
              {/* Channel Asset Usage */}
              <div style={{ background: "rgba(255,255,255,.04)", backdropFilter: "blur(20px)", border: "1px solid rgba(255,255,255,.08)", borderRadius: 16, padding: 24, boxShadow: "0 20px 40px -10px rgba(0,0,0,.4)" }}>
                <div style={{ fontSize: 19, fontWeight: 700 }}>Channel Asset Usage</div>
                <div style={{ color: "#64748b", fontSize: 14, marginTop: 6 }}>Ringkasan aset channel aktif</div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 24 }}>
                  <div style={{ background: "rgba(255,255,255,.06)", border: "1px solid rgba(255,255,255,.08)", borderRadius: 10, padding: 18 }}>
                    <div style={{ fontSize: 11, color: "#64748b" }}>Channel</div>
                    <div style={{ fontSize: 18, fontWeight: 700, marginTop: 8 }}>{activeChannel?.name || "-"}</div>
                  </div>
                  <div style={{ background: "rgba(255,255,255,.06)", border: "1px solid rgba(255,255,255,.08)", borderRadius: 10, padding: 18 }}>
                    <div style={{ fontSize: 11, color: "#64748b" }}>Total Size</div>
                    <div style={{ fontSize: 22, fontWeight: 800, marginTop: 6 }}>{fmtBytes(totalChannelSize * 1024 * 1024)}</div>
                  </div>
                </div>
              </div>
              {/* Storage Per Group */}
              <div style={{ background: "rgba(255,255,255,.04)", backdropFilter: "blur(20px)", border: "1px solid rgba(255,255,255,.08)", borderRadius: 16, padding: 24, boxShadow: "0 20px 40px -10px rgba(0,0,0,.4)" }}>
                <div style={{ fontSize: 19, fontWeight: 700 }}>Storage Per Grup</div>
                <div style={{ color: "#64748b", fontSize: 14, marginTop: 6 }}>Kapasitas per tipe aset</div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 12, marginTop: 16 }}>
                  {GROUPS.slice(0, 6).map(g => (
                    <div key={g.key} style={{ background: "rgba(255,255,255,.06)", border: "1px solid rgba(255,255,255,.08)", borderRadius: 8, padding: 12 }}>
                      <div style={{ fontSize: 10, color: "#64748b", fontWeight: 700 }}>{g.icon} {g.label}</div>
                      <div style={{ fontSize: 14, fontWeight: 700, marginTop: 4 }}>{stats[g.key]?.count || 0} file</div>
                      <div style={{ fontSize: 10, color: "#64748b" }}>{fmtBytes((stats[g.key]?.size_mb || 0) * 1024 * 1024)}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Group Cards Grid */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: 16 }}>
              {GROUPS.map(g => (
                <div
                  key={g.key}
                  onClick={() => setActiveGroup(g.key)}
                  style={{
                    display: "block", background: activeGroup === g.key ? "rgba(96,165,250,.16)" : "rgba(255,255,255,.06)",
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
                    <select
                      value={uploadGroup}
                      onChange={e => setUploadGroup(e.target.value)}
                      style={{ width: "100%", padding: "14px 18px", background: "#101a2b", border: "1px solid rgba(255,255,255,.08)", borderRadius: 10, color: "#f8fafc", fontSize: 14, fontWeight: 700, outline: "none" }}
                    >
                      {GROUPS.map(g => <option key={g.key} value={g.key} style={{ background: "#0b1220" }}>{g.label}</option>)}
                    </select>
                  </div>
                  <div>
                    <label style={{ display: "block", marginBottom: 8, fontSize: 11, fontWeight: 700, letterSpacing: 1, color: "#64748b", textTransform: "uppercase" as const }}>File</label>
                    <input
                      type="file"
                      required
                      accept="video/*,audio/*,image/*,.mp4,.mp3,.wav,.jpg,.jpeg,.png,.webp"
                      style={{ width: "100%", padding: "14px 18px", background: "rgba(255,255,255,.06)", border: "1px solid rgba(255,255,255,.08)", borderRadius: 10, color: "#fff", fontSize: 14 }}
                    />
                  </div>
                </div>
                <button
                  type="submit"
                  disabled={uploading}
                  style={{ marginTop: 16, padding: "12px 24px", borderRadius: 10, border: "none", background: "linear-gradient(135deg,#00539C,#003a6e)", color: "#FFD662", fontWeight: 700, fontSize: 14, cursor: "pointer", opacity: uploading ? .6 : 1 }}
                >
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

              <input
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Cari file..."
                style={{ width: "100%", padding: "10px 14px", fontSize: 13, background: "rgba(255,255,255,.04)", border: "1px solid rgba(255,255,255,.08)", borderRadius: 10, color: "#fff", outline: "none", marginBottom: 16 }}
              />

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
                        <th style={{ background: "rgba(255,255,255,.05)", padding: "16px 20px", textAlign: "left", fontSize: 11, fontWeight: 700, letterSpacing: 1, color: "#64748b", textTransform: "uppercase" as const }}>Filename</th>
                        <th style={{ background: "rgba(255,255,255,.05)", padding: "16px 20px", textAlign: "left", fontSize: 11, fontWeight: 700, letterSpacing: 1, color: "#64748b", textTransform: "uppercase" as const }}>Size</th>
                        <th style={{ background: "rgba(255,255,255,.05)", padding: "16px 20px", textAlign: "left", fontSize: 11, fontWeight: 700, letterSpacing: 1, color: "#64748b", textTransform: "uppercase" as const }}>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredFiles.map(f => (
                        <tr key={f.filename}>
                          <td style={{ padding: "14px 16px", borderTop: "1px solid rgba(255,255,255,.08)" }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                              <span style={{ fontSize: 16 }}>{f.filename.match(/\.(mp4|mkv|avi|mov)$/i) ? "🎥" : f.filename.match(/\.(mp3|wav)$/i) ? "🎵" : f.filename.match(/\.(jpg|jpeg|png|webp)$/i) ? "🖼️" : "📄"}</span>
                              <div>
                                <div style={{ fontWeight: 700, color: "#e0e8f0" }}>{f.filename}</div>
                              </div>
                            </div>
                          </td>
                          <td style={{ padding: "14px 16px", borderTop: "1px solid rgba(255,255,255,.08)", color: "#94a3b8" }}>{fmtBytes(f.size)}</td>
                          <td style={{ padding: "14px 16px", borderTop: "1px solid rgba(255,255,255,.08)" }}>
                            <button
                              onClick={() => handleDelete(f.filename)}
                              style={{ fontSize: 11, padding: "6px 14px", borderRadius: 6, border: "1px solid rgba(239,68,68,.2)", background: "rgba(239,68,68,.08)", color: "#ef4444", cursor: "pointer", fontWeight: 700 }}
                            >
                              🗑️ Hapus
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
