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

export default function UploadSection({ activeChannelId, uploads, channels, onReload }: { activeChannelId: number | null; uploads: UploadItem[]; channels: Channel[]; onReload: () => void }) {
  const [uploadReadyFiles, setUploadReadyFiles] = useState<{ filename: string; size: number }[]>([]);
  const [clipboardDesc, setClipboardDesc] = useState("");
  const [clipboardTags, setClipboardTags] = useState("");
  const [showBankTitle, setShowBankTitle] = useState(false);
  const [bankTitles, setBankTitles] = useState<{ id: number; title: string; used_at: string | null }[]>([]);
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [selectedFile, setSelectedFile] = useState<{ filename: string; size: number } | null>(null);
  const [uploadForm, setUploadForm] = useState({ title: '', description: '', tags: '', visibility: 'scheduled', scheduled_at: '' });

  useEffect(() => {
    if (!activeChannelId) return;
    fetch(`${API}/uploads/upload-ready?channel_id=${activeChannelId}`).then(r => r.json()).then(d => setUploadReadyFiles(d.files || []));
    fetch(`${API}/uploads/clipboard-description?channel_id=${activeChannelId}`).then(r => r.json()).then(d => setClipboardDesc(d.description || ""));
    fetch(`${API}/uploads/clipboard-tags?channel_id=${activeChannelId}`).then(r => r.json()).then(d => setClipboardTags(d.tags || ""));
  }, [activeChannelId]);

  const loadBankTitles = async () => {
    if (!activeChannelId) return;
    const resp = await fetch(`${API}/uploads/bank-title?channel_id=${activeChannelId}`);
    const data = await resp.json();
    setBankTitles(data);
    setShowBankTitle(true);
  };

  const saveClipboard = async (type: "description" | "tags") => {
    if (!activeChannelId) return;
    const content = type === "description" ? clipboardDesc : clipboardTags;
    await fetch(`${API}/uploads/clipboard-${type}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ channel_id: activeChannelId, content }),
    });
    alert("✅ Saved to pool");
  };

  const handleUploadClick = (file: { filename: string; size: number }) => {
    setSelectedFile(file);
    setUploadForm({ title: file.filename.replace(/\.[^.]+$/, ''), description: clipboardDesc, tags: clipboardTags, visibility: 'scheduled', scheduled_at: '' });
    setShowUploadModal(true);
  };

  const submitUpload = async () => {
    if (!activeChannelId || !selectedFile) return;
    if (!uploadForm.title) return alert('Title wajib diisi!');
    if (uploadForm.visibility === 'scheduled' && !uploadForm.scheduled_at) return alert('Scheduled time wajib diisi!');

    try {
      const resp = await fetch(, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          channel_id: activeChannelId,
          title: uploadForm.title,
          description: uploadForm.description,
          tags: uploadForm.tags,
          visibility: uploadForm.visibility,
          scheduled_at: uploadForm.visibility === 'scheduled' ? uploadForm.scheduled_at : null,
        }),
      });
      const data = await resp.json();
      if (data.success) {
        alert('✅ Upload berhasil dijadwalkan!');
        setShowUploadModal(false);
        setSelectedFile(null);
        onReload();
      } else {
        alert('❌ Gagal: ' + (data.detail || 'Unknown error'));
      }
    } catch (e) {
      alert('❌ Error: ' + e);
    }
  };

  const stats = {
    total: uploads.length,
    done: uploads.filter(u => u.status === "done").length,
    pending: uploads.filter(u => u.status === "pending").length,
    failed: uploads.filter(u => u.status === "failed").length,
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* Stats Cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 16 }}>
        {[{ l: "Total", v: stats.total, c: "#3b82f6" }, { l: "Sukses", v: stats.done, c: "#10b981" }, { l: "Pending", v: stats.pending, c: "#f59e0b" }, { l: "Gagal", v: stats.failed, c: "#ef4444" }].map(st => (
          <div key={st.l} style={{ ...s.card, textAlign: "center" as const }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#64748b", textTransform: "uppercase" as const }}>{st.l}</div>
            <div style={{ fontSize: 28, fontWeight: 900, marginTop: 8, color: st.c }}>{st.v}</div>
          </div>
        ))}
      </div>

      {/* Upload Ready Files */}
      <div style={{ ...s.card, padding: 0, overflow: "hidden" }}>
        <div style={{ padding: "16px 20px", borderBottom: "1px solid rgba(255,255,255,.06)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontSize: 14, fontWeight: 700 }}>📤 Upload Ready ({uploadReadyFiles.length} files)</div>
          <button onClick={loadBankTitles} style={{ fontSize: 11, padding: "4px 10px", borderRadius: 6, border: "1px solid rgba(255,255,255,.08)", background: "rgba(255,255,255,.04)", color: "#94a3b8", cursor: "pointer" }}>📋 Bank Title</button>
        </div>
        {uploadReadyFiles.length === 0 ? (
          <div style={{ padding: 40, textAlign: "center", color: "#64748b" }}>Belum ada file siap upload. Kirim dari Production dulu.</div>
        ) : (
          <table style={s.table}>
            <thead><tr>{["Filename", "Size", ""].map(h => <th key={h} style={s.th}>{h}</th>)}</tr></thead>
            <tbody>
              {uploadReadyFiles.map(f => (
                <tr key={f.filename}>
                  <td style={s.td}><span style={{ fontWeight: 700, color: "#e0e8f0" }}>🎥 {f.filename}</span></td>
                  <td style={{ ...s.td, color: "#94a3b8" }}>{fmtBytes(f.size)}</td>
                  <td style={s.td}><button onClick={() => handleUploadClick(f)} style={{ fontSize: 10, padding: "3px 8px", borderRadius: 6, border: "1px solid rgba(0,83,156,.3)", background: "rgba(0,83,156,.12)", color: "#FFD662", cursor: "pointer" }}>📤 Upload</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Clipboard Section */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <div style={s.card}>
          <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12 }}>📝 Description Clipboard</div>
          <textarea value={clipboardDesc} onChange={e => setClipboardDesc(e.target.value)} placeholder="Description template..." style={{ ...inputStyle, minHeight: 100, resize: "vertical" as const }} />
          <button onClick={() => saveClipboard("description")} style={{ marginTop: 8, ...s.btn }}>💾 Save to Pool</button>
        </div>
        <div style={s.card}>
          <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12 }}>🏷️ Tags Clipboard</div>
          <textarea value={clipboardTags} onChange={e => setClipboardTags(e.target.value)} placeholder="tag1, tag2, tag3..." style={{ ...inputStyle, minHeight: 100, resize: "vertical" as const }} />
          <button onClick={() => saveClipboard("tags")} style={{ marginTop: 8, ...s.btn }}>💾 Save to Pool</button>
        </div>
      </div>

      {/* Upload History */}
      <div style={{ ...s.card, padding: 0, overflow: "hidden" }}>
        <div style={{ padding: "16px 20px", borderBottom: "1px solid rgba(255,255,255,.06)", fontSize: 14, fontWeight: 700 }}>📋 Upload History</div>
        <table style={s.table}>
          <thead><tr>{["ID", "Title", "YouTube", "Status", "Scheduled", "Created"].map(h => <th key={h} style={s.th}>{h}</th>)}</tr></thead>
          <tbody>
            {uploads.map(u => <tr key={u.id}>
              <td style={s.td}>#{u.id}</td>
              <td style={{ ...s.td, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{u.title || "-"}</td>
              <td style={{ ...s.td, fontFamily: "monospace", color: "#94a3b8" }}>{u.youtube_video_id || "-"}</td>
              <td style={s.td}><span style={s.badge(statusColor[u.status])}>{u.status}</span></td>
              <td style={{ ...s.td, fontSize: 12, color: "#64748b" }}>{u.scheduled_at ? new Date(u.scheduled_at).toLocaleDateString("id-ID") : "-"}</td>
              <td style={{ ...s.td, fontSize: 12, color: "#64748b" }}>{new Date(u.created_at).toLocaleDateString("id-ID")}</td>
            </tr>)}
            {uploads.length === 0 && <tr><td colSpan={6} style={{ ...s.td, textAlign: "center", padding: 40, color: "#64748b" }}>Belum ada upload</td></tr>}
          </tbody>
        </table>
      </div>

      {/* Upload Modal */}
      {showUploadModal && selectedFile && (
        <div onClick={e => { if (e.target === e.currentTarget) setShowUploadModal(false); }} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.5)", backdropFilter: "blur(4px)", display: "grid", placeItems: "center", zIndex: 50 }}>
          <div style={{ background: "#101828", border: "1px solid rgba(255,255,255,.1)", borderRadius: 20, padding: 28, width: "100%", maxWidth: 500 }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 20 }}>
              <h3 style={{ fontSize: 16, fontWeight: 800, color: "#fff" }}>📤 Upload ke YouTube</h3>
              <button onClick={() => setShowUploadModal(false)} style={{ color: "#64748b", cursor: "pointer", background: "none", border: "none", fontSize: 18 }}>✕</button>
            </div>

            <div style={{ marginBottom: 16, padding: 12, background: "rgba(255,255,255,.04)", borderRadius: 8, fontSize: 13, color: "#94a3b8" }}>
              🎥 File: <strong style={{ color: "#e0e8f0" }}>{selectedFile.filename}</strong>
            </div>

            <div style={{ marginBottom: 16 }}>
              <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "#94a3b8", marginBottom: 6 }}>Title *</label>
              <input value={uploadForm.title} onChange={e => setUploadForm({ ...uploadForm, title: e.target.value })} style={inputStyle} placeholder="Video title" />
            </div>

            <div style={{ marginBottom: 16 }}>
              <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "#94a3b8", marginBottom: 6 }}>Visibility *</label>
              <select value={uploadForm.visibility} onChange={e => setUploadForm({ ...uploadForm, visibility: e.target.value })} style={inputStyle}>
                <option value="public">🌍 Public</option>
                <option value="unlisted">🔗 Unlisted</option>
                <option value="private">🔒 Private</option>
                <option value="scheduled">⏰ Scheduled</option>
              </select>
            </div>

            {uploadForm.visibility === "scheduled" && (
              <div style={{ marginBottom: 16 }}>
                <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "#94a3b8", marginBottom: 6 }}>Schedule At *</label>
                <input type="datetime-local" value={uploadForm.scheduled_at} onChange={e => setUploadForm({ ...uploadForm, scheduled_at: e.target.value })} style={inputStyle} />
                <div style={{ fontSize: 11, color: "#64748b", marginTop: 4 }}>Video akan otomatis publish pada waktu ini</div>
              </div>
            )}

            <div style={{ marginBottom: 16 }}>
              <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "#94a3b8", marginBottom: 6 }}>Description</label>
              <textarea value={uploadForm.description} onChange={e => setUploadForm({ ...uploadForm, description: e.target.value })} style={{ ...inputStyle, minHeight: 80, resize: "vertical" as const }} placeholder="Video description..." />
            </div>

            <div style={{ marginBottom: 20 }}>
              <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "#94a3b8", marginBottom: 6 }}>Tags</label>
              <input value={uploadForm.tags} onChange={e => setUploadForm({ ...uploadForm, tags: e.target.value })} style={inputStyle} placeholder="tag1, tag2, tag3..." />
            </div>

            <div style={{ display: "flex", gap: 12, justifyContent: "flex-end" }}>
              <button onClick={() => setShowUploadModal(false)} style={{ padding: "10px 20px", borderRadius: 10, border: "1px solid rgba(255,255,255,.08)", background: "rgba(255,255,255,.05)", color: "#94a3b8", fontWeight: 700, fontSize: 13, cursor: "pointer" }}>Batal</button>
              <button onClick={submitUpload} style={{ padding: "10px 20px", borderRadius: 10, border: "none", background: "linear-gradient(135deg,#6366f1,#818cf8)", color: "#fff", fontWeight: 700, fontSize: 13, cursor: "pointer" }}>📤 Upload Sekarang</button>
            </div>
          </div>
        </div>
      )}

      {/* Bank Title Modal */}
      {showBankTitle && (
        <div onClick={e => { if (e.target === e.currentTarget) setShowBankTitle(false); }} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.5)", backdropFilter: "blur(4px)", display: "grid", placeItems: "center", zIndex: 50 }}>
          <div style={{ background: "#101828", border: "1px solid rgba(255,255,255,.1)", borderRadius: 20, padding: 28, width: "100%", maxWidth: 500, maxHeight: "70vh", overflow: "auto" }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
              <h3 style={{ fontSize: 16, fontWeight: 800, color: "#fff" }}>📋 Bank Title ({bankTitles.length})</h3>
              <button onClick={() => setShowBankTitle(false)} style={{ color: "#64748b", cursor: "pointer" }}>✕</button>
            </div>
            {bankTitles.length === 0 ? (
              <div style={{ color: "#64748b", textAlign: "center", padding: 20 }}>Belum ada title di bank</div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {bankTitles.map(t => (
                  <div key={t.id} style={{ padding: "8px 12px", background: "rgba(255,255,255,.04)", borderRadius: 8, fontSize: 13, color: "#e0e8f0" }}>
                    {t.title}
                    {t.used_at && <span style={{ fontSize: 10, color: "#64748b", marginLeft: 8 }}>used: {new Date(t.used_at).toLocaleDateString("id-ID")}</span>}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Monitor Upload Section ──────────────────────────────────────

