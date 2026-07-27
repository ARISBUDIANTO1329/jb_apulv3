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

export default function MonitorUploadSection({ activeChannelId }: { activeChannelId: number | null }) {
  const [stats, setStats] = useState({ total: 0, done: 0, pending: 0, processing: 0, failed: 0 });
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!activeChannelId) return;
    const load = () => {
      setLoading(true);
      fetch(`${API}/uploads/stats?channel_id=${activeChannelId}`)
        .then(r => r.json())
        .then(d => { setStats(d); setLoading(false); })
        .catch(() => setLoading(false));
    };
    load();
    const interval = setInterval(load, 30000); // Auto-refresh every 30s
    return () => clearInterval(interval);
  }, [activeChannelId]);

  if (!activeChannelId) return <div style={s.empty}><div style={{ color: "#94a3b8" }}>Pilih channel dulu</div></div>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 12 }}>
        {[{ l: "Total", v: stats.total, c: "#3b82f6" }, { l: "Sukses", v: stats.done, c: "#10b981" }, { l: "Pending", v: stats.pending, c: "#f59e0b" }, { l: "Uploading", v: stats.processing, c: "#3b82f6" }, { l: "Gagal", v: stats.failed, c: "#ef4444" }].map(st => (
          <div key={st.l} style={{ ...s.card, textAlign: "center" as const, padding: 16 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: "#64748b", textTransform: "uppercase" as const }}>{st.l}</div>
            <div style={{ fontSize: 24, fontWeight: 900, marginTop: 4, color: st.c }}>{st.v}</div>
          </div>
        ))}
      </div>
      <div style={{ ...s.card, textAlign: "center" as const, padding: 40 }}>
        <div style={{ fontSize: 11, color: "#64748b" }}>
          {loading ? "⏳ Refreshing..." : "📡 Auto-refresh setiap 30 detik"}
        </div>
      </div>
    </div>
  );
}

// ── Pipeline Section ─────────────────────────────────────────────

