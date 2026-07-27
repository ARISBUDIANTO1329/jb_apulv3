"use client";

import { useEffect, useState } from "react";
import { API, Channel, ProductionJob, UploadItem, LiveJob, Pipeline, Page, NAV_ITEMS, fmt, statusColor } from "./types";
import ProductionSection from "./components/ProductionSection";
import UploadSection from "./components/UploadSection";
import MonitorUploadSection from "./components/MonitorUploadSection";
import PipelineSection from "./components/PipelineSection";
import LivestreamSection from "./components/LivestreamSection";
import MonitorLivestreamSection from "./components/MonitorLivestreamSection";
import MediaSection from "./components/MediaSection";

export default function App() {
  const [page, setPage] = useState<Page>("dashboard");
  const [channels, setChannels] = useState<Channel[]>([]);
  const [activeChannelId, setActiveChannelId] = useState<number | null>(null);
  const [jobs, setJobs] = useState<ProductionJob[]>([]);
  const [uploads, setUploads] = useState<UploadItem[]>([]);
  const [lives, setLives] = useState<LiveJob[]>([]);
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [newCh, setNewCh] = useState({ name: "", niche: "", youtube_channel_id: "" });
  const [tokenHealth, setTokenHealth] = useState<any>(null);

  const activeChannel = channels.find(c => c.id === activeChannelId) || null;
  const filteredJobs = activeChannelId ? jobs.filter(j => j.channel_id === activeChannelId) : jobs;
  const filteredUploads = activeChannelId ? uploads.filter(u => u.channel_id === activeChannelId) : uploads;
  const filteredLives = activeChannelId ? lives.filter(l => l.channel_id === activeChannelId) : lives;
  const filteredPipelines = activeChannelId ? pipelines.filter(p => p.channel_id === activeChannelId) : pipelines;

  const load = async () => {
    try {
      const [c, p, u, l, pl, th] = await Promise.all([
        fetch(API + "/channels").then(r => r.json()),
        fetch(API + "/production").then(r => r.json()),
        fetch(API + "/uploads/items").then(r => r.json()),
        fetch(API + "/livestream").then(r => r.json()),
        fetch(API + "/pipeline").then(r => r.json()),
        fetch(API + "/channels/token-health").then(r => r.json()).catch(() => null),
      ]);
      setChannels(c); setJobs(p); setUploads(u); setLives(l); setPipelines(pl); if (th) setTokenHealth(th);
    } catch (e) { console.error("Load error:", e); }
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const groups = NAV_ITEMS.reduce<Record<string, typeof NAV_ITEMS>>((acc, item) => {
    (acc[item.group] = acc[item.group] || []).push(item);
    return acc;
  }, {});

  const renderPage = () => {
    if (loading) return <div style={{ color: "#64748b" }}>Loading...</div>;
    switch (page) {
      case "dashboard": return <div>Dashboard</div>;
      case "media": return <MediaSection channelId={activeChannelId} channels={channels} />;
      case "production": return <ProductionSection channels={channels} jobs={filteredJobs} activeChannelId={activeChannelId} onReload={load} />;
      case "uploads": return <UploadSection activeChannelId={activeChannelId} uploads={filteredUploads} channels={channels} onReload={load} />;
      case "monitor-upload": return <MonitorUploadSection activeChannelId={activeChannelId} />;
      case "live": return <LivestreamSection channels={channels} lives={filteredLives} activeChannelId={activeChannelId} onReload={load} />;
      case "monitor-live": return <MonitorLivestreamSection activeChannelId={activeChannelId} />;
      case "pipeline": return <PipelineSection channels={channels} pipelines={filteredPipelines} activeChannelId={activeChannelId} onReload={load} />;
      default: return <div>Page not found</div>;
    }
  };

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: "#0a0e18", color: "#e0e8f0", fontFamily: "Inter,-apple-system,sans-serif" }}>
      <aside style={{ width: 240, background: "#0e1424", borderRight: "1px solid rgba(255,255,255,.06)", padding: "16px 12px" }}>
        <div style={{ padding: "12px", marginBottom: 16 }}>
          <div style={{ fontWeight: 800, fontSize: 15 }}>JB APUL v3</div>
          <div style={{ fontSize: 10, color: "#64748b" }}>YouTube Automation</div>
        </div>
        {NAV_ITEMS.map(item => (
          <button key={item.key} onClick={() => setPage(item.key)} style={{ display: "flex", alignItems: "center", gap: 10, width: "100%", padding: "10px 12px", borderRadius: 10, border: "none", background: page === item.key ? "rgba(0,83,156,.2)" : "transparent", color: page === item.key ? "#fff" : "#94a3b8", fontSize: 13, fontWeight: 600, cursor: "pointer" }}>
            <span>{item.icon}</span> {item.label}
          </button>
        ))}
      </aside>
      <main style={{ flex: 1, padding: 24 }}>
        {renderPage()}
      </main>
    </div>
  );
}
