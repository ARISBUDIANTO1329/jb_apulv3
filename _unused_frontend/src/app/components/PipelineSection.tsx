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

export default function PipelineSection({ channels, pipelines, activeChannelId, onReload }: { channels: Channel[]; pipelines: Pipeline[]; activeChannelId: number | null; onReload: () => void }) {
  const [selectedPipeline, setSelectedPipeline] = useState<number | null>(null);
  const [activeRun, setActiveRun] = useState<{ active: boolean; run_id?: number; status?: string; progress?: number; current_stage?: string } | null>(null);
  const [showUploadConfig, setShowUploadConfig] = useState(false);
  const [showLiveConfig, setShowLiveConfig] = useState(false);
  const [uploadForm, setUploadForm] = useState({ mode: "final", upload_count: 3, scheduler_time: "13:00", use_mp3: true, use_sfx: true, num_songs: 3, duration_mode: "mp3", custom_duration: "01:00:00" });
  const [liveForm, setLiveForm] = useState({ live_mode: "final", live_count: 1, live_duration_hours: 12, live_quality: "low", live_use_mp3: true, live_use_sfx: true });

  const sp = pipelines.find(p => p.id === selectedPipeline) || null;

  // Poll active run
  useEffect(() => {
    if (!selectedPipeline) return;
    const load = () => {
      fetch(`${API}/pipeline/${selectedPipeline}/active-run`)
        .then(r => r.json())
        .then(d => setActiveRun(d))
        .catch(() => {});
    };
    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, [selectedPipeline]);

  const togglePipeline = async (id: number) => {
    await fetch(`${API}/pipeline/${id}/toggle`, { method: "POST" });
    onReload();
  };

  const toggleFeature = async (id: number, feature: string) => {
    await fetch(`${API}/pipeline/${id}/toggle-feature?feature=${feature}`, { method: "POST" });
    onReload();
  };

  const runNow = async (id: number) => {
    const resp = await fetch(`${API}/pipeline/${id}/run`, { method: "POST" });
    const data = await resp.json();
    if (data.success) {
      alert(`✅ Pipeline run started (ID: ${data.run_id})`);
      setSelectedPipeline(id);
    } else {
      alert(data.detail || "Gagal start pipeline");
    }
  };

  const pauseResume = async (id: number, isActive: boolean) => {
    const action = isActive ? "pause" : "resume";
    await fetch(`${API}/pipeline/${id}/${action}`, { method: "POST" });
    onReload();
  };

  const cancelRun = async (runId: number) => {
    if (!confirm("Cancel running pipeline?")) return;
    await fetch(`${API}/pipeline/run/${runId}/cancel`, { method: "POST" });
    onReload();
  };

  const saveUploadConfig = async () => {
    if (!selectedPipeline) return;
    await fetch(`${API}/pipeline/${selectedPipeline}/save-upload`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(uploadForm),
    });
    setShowUploadConfig(false);
    onReload();
    alert("✅ Upload config saved");
  };

  const saveLiveConfig = async () => {
    if (!selectedPipeline) return;
    await fetch(`${API}/pipeline/${selectedPipeline}/save-livestream`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(liveForm),
    });
    setShowLiveConfig(false);
    onReload();
    alert("✅ Livestream config saved");
  };

  const createPipeline = async () => {
    if (!activeChannelId) return alert("Pilih channel dulu");
    const resp = await fetch(`${API}/pipeline`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ channel_id: activeChannelId }),
    });
    const data = await resp.json();
    if (data.success) {
      onReload();
      alert("✅ Pipeline created");
    } else {
      alert(data.detail || "Gagal");
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ fontSize: 14, color: "#64748b" }}>{pipelines.length} pipeline</div>
        <button onClick={createPipeline} style={s.btn}>+ Buat Pipeline</button>
      </div>

      {/* Pipeline Cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(380px,1fr))", gap: 16 }}>
        {pipelines.map(p => (
          <div key={p.id} style={{ ...s.card, borderColor: selectedPipeline === p.id ? "rgba(0,83,156,.4)" : undefined }}>
            {/* Header */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
              <div style={{ fontWeight: 700, fontSize: 15, color: "#fff" }}>{channels.find(c => c.id === p.channel_id)?.name || `Channel #${p.channel_id}`}</div>
              <div style={{ display: "flex", gap: 6 }}>
                <span onClick={() => togglePipeline(p.id)} style={{ fontSize: 10, fontWeight: 700, padding: "3px 8px", borderRadius: 6, background: p.is_active ? "rgba(16,185,129,.1)" : "rgba(100,116,139,.1)", color: p.is_active ? "#10b981" : "#64748b", cursor: "pointer" }}>{p.is_active ? "ACTIVE" : "PAUSED"}</span>
              </div>
            </div>

            {/* Config Grid */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, fontSize: 12, marginBottom: 16 }}>
              <div><span style={{ color: "#64748b" }}>Mode:</span> <span style={{ fontWeight: 700 }}>{(p.mode || "final").toUpperCase()}</span></div>
              <div><span style={{ color: "#64748b" }}>Schedule:</span> <span style={{ fontWeight: 700 }}>{p.scheduler_time || "Manual"}</span></div>
            </div>

            {/* Feature Toggles */}
            <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 16 }}>
              {/* Upload toggle */}
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 12px", background: "rgba(255,255,255,.03)", borderRadius: 8 }}>
                <span style={{ fontSize: 12, fontWeight: 600 }}>📤 Upload Harian</span>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <span style={{ fontSize: 11, color: "#64748b" }}>{p.upload_count || 3} video</span>
                  <span onClick={() => toggleFeature(p.id, "upload")} style={{ width: 36, height: 20, borderRadius: 10, background: p.upload_enabled ? "rgba(16,185,129,.3)" : "rgba(255,255,255,.08)", display: "flex", alignItems: "center", cursor: "pointer", padding: 2 }}>
                    <span style={{ width: 16, height: 16, borderRadius: "50%", background: p.upload_enabled ? "#10b981" : "#64748b", transform: p.upload_enabled ? "translateX(16px)" : "translateX(0)", transition: "all .2s" }} />
                  </span>
                </div>
              </div>

              {/* Live toggle */}
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 12px", background: "rgba(255,255,255,.03)", borderRadius: 8 }}>
                <span style={{ fontSize: 12, fontWeight: 600 }}>🔴 Livestream Harian</span>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <span style={{ fontSize: 11, color: "#64748b" }}>{p.live_duration_hours || 12}h</span>
                  <span onClick={() => toggleFeature(p.id, "live")} style={{ width: 36, height: 20, borderRadius: 10, background: p.live_enabled ? "rgba(16,185,129,.3)" : "rgba(255,255,255,.08)", display: "flex", alignItems: "center", cursor: "pointer", padding: 2 }}>
                    <span style={{ width: 16, height: 16, borderRadius: "50%", background: p.live_enabled ? "#10b981" : "#64748b", transform: p.live_enabled ? "translateX(16px)" : "translateX(0)", transition: "all .2s" }} />
                  </span>
                </div>
              </div>
            </div>

            {/* Actions */}
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" as const }}>
              <button onClick={() => { setSelectedPipeline(p.id); setShowUploadConfig(true); }} style={{ fontSize: 10, padding: "4px 10px", borderRadius: 6, border: "1px solid rgba(0,83,156,.3)", background: "rgba(0,83,156,.12)", color: "#FFD662", cursor: "pointer" }}>📤 Upload Config</button>
              <button onClick={() => { setSelectedPipeline(p.id); setShowLiveConfig(true); }} style={{ fontSize: 10, padding: "4px 10px", borderRadius: 6, border: "1px solid rgba(239,68,68,.2)", background: "rgba(239,68,68,.08)", color: "#ef4444", cursor: "pointer" }}>🔴 Live Config</button>
              <button onClick={() => runNow(p.id)} style={{ fontSize: 10, padding: "4px 10px", borderRadius: 6, border: "1px solid rgba(16,185,129,.3)", background: "rgba(16,185,129,.12)", color: "#10b981", cursor: "pointer" }}>▶️ Run Now</button>
              <button onClick={() => pauseResume(p.id, p.is_active)} style={{ fontSize: 10, padding: "4px 10px", borderRadius: 6, border: "1px solid rgba(255,255,255,.08)", background: "rgba(255,255,255,.04)", color: "#94a3b8", cursor: "pointer" }}>{p.is_active ? "⏸ Pause" : "▶️ Resume"}</button>
            </div>

            {/* Active Run Indicator */}
            {selectedPipeline === p.id && activeRun?.active && (
              <div style={{ marginTop: 12, padding: "10px 14px", background: "rgba(59,130,246,.08)", border: "1px solid rgba(59,130,246,.2)", borderRadius: 10 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div>
                    <div style={{ fontSize: 11, fontWeight: 700, color: "#60a5fa" }}>🔄 Running: {activeRun.current_stage || activeRun.status}</div>
                    <div style={{ fontSize: 10, color: "#64748b", marginTop: 2 }}>Progress: {activeRun.progress || 0}%</div>
                  </div>
                  <button onClick={() => activeRun.run_id && cancelRun(activeRun.run_id)} style={{ fontSize: 10, padding: "3px 8px", borderRadius: 6, border: "1px solid rgba(239,68,68,.2)", background: "rgba(239,68,68,.08)", color: "#ef4444", cursor: "pointer" }}>❌ Cancel</button>
                </div>
              </div>
            )}
          </div>
        ))}
        {pipelines.length === 0 && <div style={s.empty}><div style={{ fontSize: 40, marginBottom: 12 }}>⚡</div><div style={{ color: "#94a3b8" }}>Belum ada pipeline</div></div>}
      </div>

      {/* Upload Config Modal */}
      {showUploadConfig && sp && (
        <div onClick={e => { if (e.target === e.currentTarget) setShowUploadConfig(false); }} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.5)", backdropFilter: "blur(4px)", display: "grid", placeItems: "center", zIndex: 50 }}>
          <div style={{ background: "#101828", border: "1px solid rgba(255,255,255,.1)", borderRadius: 20, padding: 28, width: "100%", maxWidth: 560, maxHeight: "85vh", overflow: "auto" }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 20 }}>
              <h3 style={{ fontSize: 16, fontWeight: 800, color: "#fff" }}>📤 Edit Upload Config</h3>
              <button onClick={() => setShowUploadConfig(false)} style={{ color: "#64748b", cursor: "pointer" }}>✕</button>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
              {/* Section: Mode */}
              <div style={{ padding: 16, background: "rgba(255,255,255,.03)", border: "1px solid rgba(255,255,255,.06)", borderRadius: 12 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: "#FFD662", marginBottom: 12, textTransform: "uppercase" as const }}>⚙️ Mode Pipeline</div>
                <div>
                  <label style={labelStyle}>Mode</label>
                  <select value={uploadForm.mode} onChange={e => setUploadForm({ ...uploadForm, mode: e.target.value })} style={inputStyle}>
                    <option value="final">Final — Video sudah jadi (upload random dari Video)</option>
                    <option value="static">Static — Raw → Seamless Loop (proses raw dulu)</option>
                    <option value="dynamic">Dynamic — Raw → Merge (gabung beberapa raw)</option>
                  </select>
                </div>
              </div>

              {/* Section: Upload Schedule */}
              <div style={{ padding: 16, background: "rgba(255,255,255,.03)", border: "1px solid rgba(255,255,255,.06)", borderRadius: 12 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: "#FFD662", marginBottom: 12, textTransform: "uppercase" as const }}>📤 Upload Schedule</div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                  <div>
                    <label style={labelStyle}>Upload per Hari</label>
                    <input type="number" min={1} max={3} value={uploadForm.upload_count} onChange={e => setUploadForm({ ...uploadForm, upload_count: +e.target.value })} style={inputStyle} />
                    <div style={{ fontSize: 10, color: "#64748b", marginTop: 4 }}>Maks 3 video/hari</div>
                  </div>
                  <div>
                    <label style={labelStyle}>Jam Upload (WIB)</label>
                    <select value={uploadForm.scheduler_time} onChange={e => setUploadForm({ ...uploadForm, scheduler_time: e.target.value })} style={inputStyle}>
                      {Array.from({ length: 24 }, (_, i) => i).map(h => (
                        <option key={h} value={`${String(h).padStart(2, "0")}:00`}>{String(h).padStart(2, "0")}:00 WIB</option>
                      ))}
                    </select>
                  </div>
                </div>
              </div>

              {/* Section: Audio */}
              <div style={{ padding: 16, background: "rgba(255,255,255,.03)", border: "1px solid rgba(255,255,255,.06)", borderRadius: 12 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: "#FFD662", marginBottom: 12, textTransform: "uppercase" as const }}>🎵 Audio Settings</div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                  <div>
                    <label style={labelStyle}>Jumlah Lagu</label>
                    <input type="number" min={1} max={10} value={uploadForm.num_songs} onChange={e => setUploadForm({ ...uploadForm, num_songs: +e.target.value })} style={inputStyle} />
                  </div>
                  <div>
                    <label style={labelStyle}>Mode Durasi</label>
                    <select value={uploadForm.duration_mode} onChange={e => setUploadForm({ ...uploadForm, duration_mode: e.target.value })} style={inputStyle}>
                      <option value="mp3">Ikuti MP3 (otomatis)</option>
                      <option value="manual">Manual (tentukan sendiri)</option>
                    </select>
                  </div>
                </div>
                {uploadForm.duration_mode === "manual" && (
                  <div style={{ marginTop: 12 }}>
                    <label style={labelStyle}>Custom Duration (HH:MM:SS)</label>
                    <input value={uploadForm.custom_duration} onChange={e => setUploadForm({ ...uploadForm, custom_duration: e.target.value })} placeholder="01:00:00" style={inputStyle} />
                  </div>
                )}
                <div style={{ display: "flex", gap: 16, marginTop: 12 }}>
                  <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, cursor: "pointer" }}>
                    <input type="checkbox" checked={uploadForm.use_mp3} onChange={e => setUploadForm({ ...uploadForm, use_mp3: e.target.checked })} /> Pakai MP3
                  </label>
                  <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, cursor: "pointer" }}>
                    <input type="checkbox" checked={uploadForm.use_sfx} onChange={e => setUploadForm({ ...uploadForm, use_sfx: e.target.checked })} /> Pakai SFX
                  </label>
                </div>
              </div>
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 20 }}>
              <button onClick={() => setShowUploadConfig(false)} style={{ padding: "10px 20px", borderRadius: 10, border: "1px solid rgba(255,255,255,.08)", background: "rgba(255,255,255,.05)", color: "#94a3b8", fontWeight: 700, fontSize: 13, cursor: "pointer" }}>Batal</button>
              <button onClick={saveUploadConfig} style={{ padding: "10px 20px", borderRadius: 10, border: "none", background: "linear-gradient(135deg,#16a34a,#22c55e)", color: "#fff", fontWeight: 700, fontSize: 13, cursor: "pointer" }}>💾 Simpan Upload Config</button>
            </div>
          </div>
        </div>
      )}

      {/* Live Config Modal */}
      {showLiveConfig && sp && (
        <div onClick={e => { if (e.target === e.currentTarget) setShowLiveConfig(false); }} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.5)", backdropFilter: "blur(4px)", display: "grid", placeItems: "center", zIndex: 50 }}>
          <div style={{ background: "#101828", border: "1px solid rgba(255,255,255,.1)", borderRadius: 20, padding: 28, width: "100%", maxWidth: 560, maxHeight: "85vh", overflow: "auto" }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 20 }}>
              <h3 style={{ fontSize: 16, fontWeight: 800, color: "#fff" }}>🔴 Edit Livestream Config</h3>
              <button onClick={() => setShowLiveConfig(false)} style={{ color: "#64748b", cursor: "pointer" }}>✕</button>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
              {/* Section: Mode */}
              <div style={{ padding: 16, background: "rgba(255,255,255,.03)", border: "1px solid rgba(255,255,255,.06)", borderRadius: 12 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: "#ef4444", marginBottom: 12, textTransform: "uppercase" as const }}>⚙️ Mode Livestream</div>
                <div>
                  <label style={labelStyle}>Mode</label>
                  <select value={liveForm.live_mode} onChange={e => setLiveForm({ ...liveForm, live_mode: e.target.value })} style={inputStyle}>
                    <option value="final">Final — Video sudah jadi (random dari Video)</option>
                    <option value="static">Static — Raw → Seamless Loop</option>
                    <option value="dynamic">Dynamic — Raw → Merge</option>
                  </select>
                </div>
              </div>

              {/* Section: Livestream Settings */}
              <div style={{ padding: 16, background: "rgba(255,255,255,.03)", border: "1px solid rgba(255,255,255,.06)", borderRadius: 12 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: "#ef4444", marginBottom: 12, textTransform: "uppercase" as const }}>🔴 Livestream Settings</div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
                  <div>
                    <label style={labelStyle}>Durasi (jam)</label>
                    <input type="number" min={1} max={72} value={liveForm.live_duration_hours} onChange={e => setLiveForm({ ...liveForm, live_duration_hours: +e.target.value })} style={inputStyle} />
                  </div>
                  <div>
                    <label style={labelStyle}>Jumlah/Hari</label>
                    <input type="number" min={1} max={5} value={liveForm.live_count} onChange={e => setLiveForm({ ...liveForm, live_count: +e.target.value })} style={inputStyle} />
                  </div>
                  <div>
                    <label style={labelStyle}>Quality</label>
                    <select value={liveForm.live_quality} onChange={e => setLiveForm({ ...liveForm, live_quality: e.target.value })} style={inputStyle}>
                      <option value="low">Low (720p, 2500k)</option>
                      <option value="high">High (1080p, 3500k)</option>
                    </select>
                  </div>
                </div>
              </div>

              {/* Section: Audio */}
              <div style={{ padding: 16, background: "rgba(255,255,255,.03)", border: "1px solid rgba(255,255,255,.06)", borderRadius: 12 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: "#ef4444", marginBottom: 12, textTransform: "uppercase" as const }}>🎵 Audio On-the-Fly</div>
                <div style={{ display: "flex", gap: 16 }}>
                  <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, cursor: "pointer" }}>
                    <input type="checkbox" checked={liveForm.live_use_mp3} onChange={e => setLiveForm({ ...liveForm, live_use_mp3: e.target.checked })} /> Pakai MP3
                  </label>
                  <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, cursor: "pointer" }}>
                    <input type="checkbox" checked={liveForm.live_use_sfx} onChange={e => setLiveForm({ ...liveForm, live_use_sfx: e.target.checked })} /> Pakai SFX
                  </label>
                </div>
                <div style={{ fontSize: 10, color: "#64748b", marginTop: 8 }}>Audio akan di-mix on-the-fly saat livestream berjalan</div>
              </div>
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 20 }}>
              <button onClick={() => setShowLiveConfig(false)} style={{ padding: "10px 20px", borderRadius: 10, border: "1px solid rgba(255,255,255,.08)", background: "rgba(255,255,255,.05)", color: "#94a3b8", fontWeight: 700, fontSize: 13, cursor: "pointer" }}>Batal</button>
              <button onClick={saveLiveConfig} style={{ padding: "10px 20px", borderRadius: 10, border: "none", background: "linear-gradient(135deg,#dc2626,#ef4444)", color: "#fff", fontWeight: 700, fontSize: 13, cursor: "pointer" }}>💾 Simpan Livestream Config</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Livestream Section ──────────────────────────────────────────

