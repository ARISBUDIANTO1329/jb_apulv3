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

export default function MonitorLivestreamSection({ activeChannelId }: { activeChannelId: number | null }) {
  const [monitors, setMonitors] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!activeChannelId) return;
    const load = () => {
      setLoading(true);
      fetch(`${API}/livestream/monitor?channel_id=${activeChannelId}`)
        .then(r => r.json())
        .then(d => { setMonitors(d.monitors || []); setLoading(false); })
        .catch(() => setLoading(false));
    };
    load();
    const interval = setInterval(load, 10000); // Refresh every 10s
    return () => clearInterval(interval);
  }, [activeChannelId]);

  const healthColor: Record<string, string> = { healthy: "#10b981", stale: "#f59e0b", dead: "#ef4444", unknown: "#64748b" };
  const healthLabel: Record<string, string> = { healthy: "HEALTHY", stale: "STALE", dead: "DEAD", unknown: "UNKNOWN" };

  const stopJob = async (jobId: number) => {
    if (!confirm("Stop livestream ini?")) return;
    await fetch(`${API}/livestream/${jobId}/stop`, { method: "POST" });
    // Reload after a short delay to let worker process
    setTimeout(() => {
      fetch(`${API}/livestream/monitor?channel_id=${activeChannelId}`)
        .then(r => r.json())
        .then(d => setMonitors(d.monitors || []));
    }, 2000);
  };

  if (!activeChannelId) return <div style={s.empty}><div style={{ color: "#94a3b8" }}>Pilih channel dulu</div></div>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div style={{ ...s.card }}>
        <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 12 }}>
          📺 Livestream Monitor {loading && <span style={{ fontSize: 11, color: "#64748b", marginLeft: 8 }}>refreshing...</span>}
        </div>
        {monitors.length === 0 ? (
          <div style={{ textAlign: "center", padding: 40, color: "#64748b" }}>Tidak ada livestream yang sedang berjalan</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {monitors.map((m: any) => (
              <div key={m.job_id} style={{
                padding: 20, borderRadius: 16,
                background: m.health === "healthy" ? "rgba(16,185,129,.06)" : m.health === "stale" ? "rgba(245,158,11,.06)" : "rgba(239,68,68,.06)",
                border: `1px solid ${m.health === "healthy" ? "rgba(16,185,129,.2)" : m.health === "stale" ? "rgba(245,158,11,.2)" : "rgba(239,68,68,.2)"}`,
              }}>
                {/* Header */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                  <div>
                    <div style={{ fontWeight: 700, color: "#fff", fontSize: 15 }}>🔴 {m.title || `Livestream #${m.job_id}`}</div>
                    <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 4 }}>
                      Quality: {m.quality} • Duration: {m.duration} / {m.duration_hours}h • Broadcast: {m.broadcast_id || "-"}
                    </div>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{
                      fontSize: 11, fontWeight: 700, padding: "4px 12px", borderRadius: 20,
                      background: `${healthColor[m.health] || "#64748b"}20`,
                      color: healthColor[m.health] || "#64748b",
                    }}>
                      <span style={{
                        display: "inline-block", width: 6, height: 6, borderRadius: "50%",
                        background: healthColor[m.health] || "#64748b", marginRight: 6,
                        animation: m.health === "healthy" ? "pulse 1.5s infinite" : "none",
                      }} />
                      {healthLabel[m.health] || m.health}
                    </span>
                    <button onClick={() => stopJob(m.job_id)} style={{
                      fontSize: 11, padding: "4px 12px", borderRadius: 8,
                      border: "1px solid rgba(239,68,68,.3)", background: "rgba(239,68,68,.1)",
                      color: "#ef4444", cursor: "pointer", fontWeight: 600,
                    }}>⏹ Stop</button>
                  </div>
                </div>

                {/* Stats Grid */}
                <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 12 }}>
                  <div style={{ padding: "10px 12px", background: "rgba(255,255,255,.04)", borderRadius: 10 }}>
                    <div style={{ fontSize: 10, color: "#64748b", fontWeight: 600, textTransform: "uppercase" }}>Bitrate</div>
                    <div style={{ fontSize: 16, fontWeight: 700, color: "#fff", marginTop: 2 }}>{m.current_bitrate ? `${m.current_bitrate} kbps` : "-"}</div>
                  </div>
                  <div style={{ padding: "10px 12px", background: "rgba(255,255,255,.04)", borderRadius: 10 }}>
                    <div style={{ fontSize: 10, color: "#64748b", fontWeight: 600, textTransform: "uppercase" }}>FPS</div>
                    <div style={{ fontSize: 16, fontWeight: 700, color: "#fff", marginTop: 2 }}>{m.current_fps || "-"}</div>
                  </div>
                  <div style={{ padding: "10px 12px", background: "rgba(255,255,255,.04)", borderRadius: 10 }}>
                    <div style={{ fontSize: 10, color: "#64748b", fontWeight: 600, textTransform: "uppercase" }}>Viewers</div>
                    <div style={{ fontSize: 16, fontWeight: 700, color: "#fff", marginTop: 2 }}>{m.viewer_count ?? "-"}</div>
                  </div>
                  <div style={{ padding: "10px 12px", background: "rgba(255,255,255,.04)", borderRadius: 10 }}>
                    <div style={{ fontSize: 10, color: "#64748b", fontWeight: 600, textTransform: "uppercase" }}>Frame Drops</div>
                    <div style={{ fontSize: 16, fontWeight: 700, color: m.frame_drop_count > 0 ? "#f59e0b" : "#fff", marginTop: 2 }}>{m.frame_drop_count ?? 0}</div>
                  </div>
                  <div style={{ padding: "10px 12px", background: "rgba(255,255,255,.04)", borderRadius: 10 }}>
                    <div style={{ fontSize: 10, color: "#64748b", fontWeight: 600, textTransform: "uppercase" }}>Last Check</div>
                    <div style={{ fontSize: 12, fontWeight: 700, color: "#fff", marginTop: 2 }}>{m.health_age_seconds ? `${m.health_age_seconds}s ago` : "-"}</div>
                  </div>
                </div>

                {/* Error */}
                {m.error_message && (
                  <div style={{ marginTop: 10, padding: "8px 12px", background: "rgba(239,68,68,.08)", borderRadius: 8, fontSize: 12, color: "#ef4444" }}>
                    ⚠️ {m.error_message}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

