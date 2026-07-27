'use client';

import { useEffect, useState } from 'react';
import { API, Channel, ProductionJob, fmt, statusColor } from '../types';

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

const methodLabel: Record<string, string> = { ready_video: '🎬 Final Production', raw_video_auto_seamless: '🔄 Auto Seamless', merge_video: '🎞️ Dynamic Merge' };
const methodColor: Record<string, string> = { ready_video: '#6366f1', raw_video_auto_seamless: '#22c55e', merge_video: '#f59e0b' };

export default function ProductionSection({ channels, jobs, activeChannelId, onReload }: {
  channels: Channel[]; jobs: ProductionJob[]; activeChannelId: number | null; onReload: () => void;
}) {
  const [prodMethod, setProdMethod] = useState<'ready_video' | 'raw_video_auto_seamless' | 'merge_video'>('ready_video');
  const [submitting, setSubmitting] = useState(false);
  const [runtimeStatus, setRuntimeStatus] = useState<{ orchestrator: boolean; ffmpeg: boolean; worker_log: string[] } | null>(null);
  const [form, setForm] = useState({
    video_source: '', num_songs: 3, use_mp3: true, use_sfx: true,
    mp3_file: '', sfx_file: '', intro_file: '',
    duration_mode: 'mp3', custom_duration: '01:00:00',
    merge_count: 10, dynamic_output_count: 1,
    merge_resolution: '1920x1080', merge_transition_enabled: true,
    merge_transition_name: 'fade', merge_transition_duration: 1.0, merge_speed: 1.0,
  });

  useEffect(() => {
    if (!activeChannelId) return;
    const loadRuntime = async () => {
      try {
        const resp = await fetch();
        const data = await resp.json();
        setRuntimeStatus(data);
      } catch {}
    };
    loadRuntime();
    const interval = setInterval(loadRuntime, 5000);
    return () => clearInterval(interval);
  }, [activeChannelId]);

  const submitJob = async (skipCooldown = false) => {
    if (!activeChannelId) return alert('Pilih channel dulu');
    setSubmitting(true);
    try {
      const resp = await fetch(/"production", {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ channel_id: activeChannelId, production_method: prodMethod, ...form, skip_cooldown: skipCooldown }),
      });
      const data = await resp.json();
      if (data.success) {
        onReload();
        setForm({ ...form, video_source: '' });
      } else {
        alert(data.detail || 'Gagal membuat job');
      }
    } catch { alert('Error'); }
    setSubmitting(false);
  };

  const deleteJob = async (id: number) => {
    if (!confirm('Hapus job ini?')) return;
    await fetch(, { method: 'DELETE' });
    onReload();
  };

  const deleteAllJobs = async (method: string) => {
    if (!confirm()) return;
    await fetch(, { method: 'DELETE' });
    onReload();
  };

  const sendToUploadReady = async (id: number) => {
    try {
      const resp = await fetch(/"production", { method: 'POST' });
      const data = await resp.json();
      if (data.success) {
        alert();
        onReload();
      } else {
        alert(data.detail || 'Gagal');
      }
    } catch { alert('Error'); }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Production Form */}
      <div style={s.card}>
        <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 16 }}>🎬 Production</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <div>
            <label style={{ display: 'block', marginBottom: 6, fontSize: 11, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '.04em' }}>Method</label>
            <select value={prodMethod} onChange={e => setProdMethod(e.target.value as any)} style={inputStyle}>
              <option value=ready_video>🎬 Final Production</option>
              <option value=raw_video_auto_seamless>🔄 Auto Seamless</option>
              <option value=merge_video>🎞️ Dynamic Merge</option>
            </select>
          </div>
          <div>
            <label style={{ display: 'block', marginBottom: 6, fontSize: 11, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '.04em' }}>Video Source</label>
            <input value={form.video_source} onChange={e => setForm({ ...form, video_source: e.target.value })} placeholder=video.mp4 style={inputStyle} />
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
          <button onClick={() => submitJob(false)} disabled={submitting || !activeChannelId} style={{ ...s.btn, opacity: submitting ? 0.6 : 1 }}>
            {submitting ? '⏳ ...' : '⚡ Start'}
          </button>
          {prodMethod !== 'merge_video' && (
            <button onClick={() => submitJob(true)} disabled={submitting || !activeChannelId} style={{ ...s.btn, background: 'rgba(16,185,129,.12)', borderColor: 'rgba(16,185,129,.3)', color: '#10b981', opacity: submitting ? 0.6 : 1 }}>
              {submitting ? '⏳ ...' : '⚡ Start All (skip cooldown)'}
            </button>
          )}
        </div>
      </div>

      {/* Job Monitor */}
      <div style={{ ...s.card, padding: 0, overflow: 'hidden' }}>
        <div style={{ padding: '16px 20px', borderBottom: '1px solid rgba(255,255,255,.06)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ fontSize: 14, fontWeight: 700 }}>Production Monitor</div>
          <div style={{ display: 'flex', gap: 8 }}>
            <span style={{ fontSize: 11, color: '#64748b' }}>{jobs.length} jobs</span>
            <button onClick={() => deleteAllJobs('final')} style={{ fontSize: 10, padding: '3px 8px', borderRadius: 6, border: '1px solid rgba(239,68,68,.2)', background: 'rgba(239,68,68,.08)', color: '#ef4444', cursor: 'pointer' }}>🗑️ Clear Final</button>
            <button onClick={() => deleteAllJobs('dynamic')} style={{ fontSize: 10, padding: '3px 8px', borderRadius: 6, border: '1px solid rgba(239,68,68,.2)', background: 'rgba(239,68,68,.08)', color: '#ef4444', cursor: 'pointer' }}>🗑️ Clear Dynamic</button>
          </div>
        </div>
        <table style={s.table}>
          <thead><tr>{['ID', 'Method', 'Source', 'Status', 'Audio', 'Video', 'Final', 'Progress', 'Actions'].map(h => <th key={h} style={s.th}>{h}</th>)}</tr></thead>
          <tbody>
            {jobs.map(j => (
              <tr key={j.id}>
                <td style={s.td}>#{j.id}</td>
                <td style={s.td}><span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 6, background: , color: methodColor[j.production_method] || '#3b82f6' }}>{methodLabel[j.production_method] || j.production_method}</span></td>
                <td style={{ ...s.td, fontSize: 12, color: '#94a3b8', fontFamily: 'monospace', maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{j.video_source || '-'}</td>
                <td style={s.td}><span style={s.badge(statusColor[j.status])}>{j.status}</span></td>
                <td style={s.td}><span style={{ fontSize: 10, color: j.audio_status === 'done' ? '#10b981' : '#64748b' }}>{j.audio_status || '-'}</span></td>
                <td style={s.td}><span style={{ fontSize: 10, color: j.video_status === 'done' ? '#10b981' : '#64748b' }}>{j.video_status || '-'}</span></td>
                <td style={s.td}><span style={{ fontSize: 10, color: j.final_status === 'done' ? '#10b981' : j.final_status === 'failed' ? '#ef4444' : '#64748b' }}>{j.final_status || '-'}</span></td>
                <td style={s.td}>
                  <div style={{ width: 80, height: 6, background: 'rgba(255,255,255,.06)', borderRadius: 3, overflow: 'hidden' }}>
                    <div style={{ width: , height: '100%', background: j.final_status === 'done' ? '#10b981' : j.status === 'failed' ? '#ef4444' : '#3b82f6', borderRadius: 3 }} />
                  </div>
                  {j.process_status && <div style={{ fontSize: 9, color: '#64748b', marginTop: 2 }}>{j.process_status}</div>}
                </td>
                <td style={s.td}>
                  <div style={{ display: 'flex', gap: 4 }}>
                    {j.final_status === 'done' && (
                      <button onClick={() => sendToUploadReady(j.id)} style={{ fontSize: 10, padding: '3px 8px', borderRadius: 6, border: '1px solid rgba(16,185,129,.2)', background: 'rgba(16,185,129,.08)', color: '#10b981', cursor: 'pointer' }}>📤</button>
                    )}
                    <button onClick={() => deleteJob(j.id)} style={{ fontSize: 10, padding: '3px 8px', borderRadius: 6, border: '1px solid rgba(255,255,255,.06)', background: 'transparent', color: '#64748b', cursor: 'pointer' }}>🗑️</button>
                  </div>
                </td>
              </tr>
            ))}
            {jobs.length === 0 && <tr><td colSpan={9} style={s.empty}>Belum ada production job</td></tr>}
          </tbody>
        </table>
      </div>

      {/* Worker Log */}
      {runtimeStatus?.worker_log && runtimeStatus.worker_log.length > 0 && (
        <div style={{ ...s.card, padding: 0, overflow: 'hidden' }}>
          <div style={{ padding: '12px 16px', borderBottom: '1px solid rgba(255,255,255,.06)', fontSize: 13, fontWeight: 700 }}>📋 Worker Log (last 40 lines)</div>
          <pre style={{ padding: 16, margin: 0, fontSize: 11, color: '#94a3b8', fontFamily: 'monospace', maxHeight: 300, overflow: 'auto', lineHeight: 1.6, background: 'rgba(0,0,0,.2)' }}>
            {runtimeStatus.worker_log.join('\n')}
          </pre>
        </div>
      )}
    </div>
  );
}
