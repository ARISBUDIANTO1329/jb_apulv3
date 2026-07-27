// TypeScript Interfaces for JB APUL v3

export interface Channel {
  id: number; name: string; youtube_channel_id: string | null;
  status: string; niche: string | null; subscriber_count: number;
  total_views: number; video_count: number; stream_key: string | null;
  proxy_host: string | null; chrome_profile: string | null;
}

export interface ProductionJob {
  id: number; channel_id: number; video_source: string | null;
  output_filename: string | null; status: string; progress: number;
  audio_status: string; video_status: string; final_status: string;
  production_method: string; error_message: string | null;
  process_status: string | null; created_at: string;
}

export interface UploadItem {
  id: number; channel_id: number; title: string | null;
  youtube_video_id: string | null; status: string;
  scheduled_at: string | null; created_at: string;
}

export interface LiveJob {
  id: number; channel_id: number; title: string | null;
  status: string; health_status?: string; duration_hours: number;
  quality: string; process_id: number | null; broadcast_id?: string;
  current_bitrate?: number; current_fps?: number; viewer_count?: number;
  frame_drop_count?: number; reconnect_count?: number;
  last_health_check?: string; error_message?: string;
  started_at?: string; created_at: string;
}

export interface Pipeline {
  id: number; channel_id: number; mode: string;
  upload_enabled: boolean; live_enabled: boolean;
  scheduler_time: string | null; is_active: boolean;
}

export type Page = 'dashboard' | 'media' | 'production' | 'uploads' | 'monitor-upload' | 'live' | 'monitor-live' | 'pipeline';

export const API = '/api';

export const fmt = (n: number) => n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'K' : String(n);

export const statusColor: Record<string, string> = {
  pending: '#f59e0b', processing: '#3b82f6', done: '#10b981',
  failed: '#ef4444', running: '#10b981', stopped: '#6b7280',
  active: '#10b981', paused: '#f59e0b', dropped: '#ef4444', scheduled: '#3b82f6'
};

export const NAV_ITEMS: { key: Page; icon: string; label: string; group: string }[] = [
  { key: 'dashboard', icon: '📊', label: 'Dashboard', group: 'Menu' },
  { key: 'media', icon: '🗂️', label: 'Media Library', group: 'Menu' },
  { key: 'production', icon: '🎬', label: 'Production', group: 'Menu' },
  { key: 'uploads', icon: '📤', label: 'Upload', group: 'Upload' },
  { key: 'monitor-upload', icon: '📡', label: 'Monitor Upload', group: 'Upload' },
  { key: 'live', icon: '🔴', label: 'Start Live', group: 'Livestream' },
  { key: 'monitor-live', icon: '📺', label: 'Monitor Livestream', group: 'Livestream' },
  { key: 'pipeline', icon: '⚡', label: 'Pipeline', group: 'Automation' },
];

export const MEDIA_GROUPS = [
  { key: 'video', label: 'Video', desc: 'Footage video utama', icon: '🎬' },
  { key: 'video-raw', label: 'Video Raw', desc: 'Video mentah sebelum proses seamless', icon: '🎥' },
  { key: 'video-live', label: 'Video Live', desc: 'Footage hasil live', icon: '📹' },
  { key: 'livestream-ready', label: 'Livestream Ready', desc: 'Video siap untuk livestream', icon: '🔴' },
  { key: 'upload_ready', label: 'Upload Ready', desc: 'Video final siap upload YouTube', icon: '📤' },
  { key: 'mp3', label: 'MP3', desc: 'Audio / musik / voice', icon: '🎵' },
  { key: 'sfx', label: 'SFX', desc: 'Efek suara pendek', icon: '🔊' },
  { key: 'intro', label: 'Intro', desc: 'Video pembuka', icon: '🎬' },
  { key: 'thumbnail', label: 'Thumbnail', desc: 'Gambar thumbnail', icon: '🖼️' },
  { key: 'metadata', label: 'Metadata', desc: 'File metadata pendukung', icon: '📝' },
];

export const fmtBytes = (b: number) => {
  if (b <= 0) return '0 B';
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.min(Math.floor(Math.log(b) / Math.log(1024)), u.length - 1);
  return (b / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1) + ' ' + u[i];
};
