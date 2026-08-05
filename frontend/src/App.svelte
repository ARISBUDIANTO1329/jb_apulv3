<script>
  import { onMount } from 'svelte'

  // State
  let channels = []
  let selectedChannelId = null
  let selectedChannel = null
  let activeTab = 'overview'

  // Data
  let analytics = null
  let performance = []
  let intelligence = null
  let titleSuggestions = []
  let titleTopic = ''

  // UI state
  let loading = { channels: false, analytics: false, performance: false, intelligence: false, titles: false }
  let error = null

  const api = async (path, opts = {}) => {
    const url = window.location.origin + '/api' + path
    const r = await fetch(url, {
      headers: { 'Content-Type': 'application/json' },
      ...opts
    })
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    return r.json()
  }

  // Load channels on mount
  onMount(async () => {
    loading.channels = true
    try {
      const result = await api('/channels')
      channels = result.channels || result || []
    } catch (e) {
      error = e.message
    }
    loading.channels = false
  })

  // When channel selected, load all data
  $: if (selectedChannelId) {
    selectedChannel = channels.find(c => c.id === selectedChannelId)
    loadAllData()
  }

  async function loadAllData() {
    if (!selectedChannelId) return
    await Promise.all([
      loadAnalytics(),
      loadPerformance(),
      loadIntelligence(),
    ])
  }

  async function loadAnalytics() {
    loading.analytics = true
    try {
      analytics = await api(`/youtube/analytics/${selectedChannelId}?days=30`)
    } catch (e) {
      console.error('Analytics error:', e)
    }
    loading.analytics = false
  }

  async function loadPerformance() {
    loading.performance = true
    try {
      const result = await api(`/youtube/performance/${selectedChannelId}`)
      performance = result.videos || []
    } catch (e) {
      console.error('Performance error:', e)
    }
    loading.performance = false
  }

  async function loadIntelligence() {
    loading.intelligence = true
    try {
      intelligence = await api(`/ai/intelligence/${selectedChannelId}`)
    } catch (e) {
      console.error('Intelligence error:', e)
    }
    loading.intelligence = false
  }

  async function takeSnapshot() {
    if (!selectedChannelId) return
    loading.performance = true
    try {
      await api(`/youtube/snapshot/${selectedChannelId}`, { method: 'POST' })
      await Promise.all([loadPerformance(), loadIntelligence()])
    } catch (e) {
      error = e.message
    }
    loading.performance = false
  }

  async function suggestTitles() {
    if (!selectedChannelId || !titleTopic.trim()) return
    loading.titles = true
    try {
      const result = await api('/ai/suggest-titles', {
        method: 'POST',
        body: JSON.stringify({
          channel_id: selectedChannelId,
          topic: titleTopic,
          count: 5
        })
      })
      titleSuggestions = result.suggestions || []
    } catch (e) {
      error = e.message
    }
    loading.titles = false
  }

  function formatNumber(n) {
    if (!n) return '0'
    if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M'
    if (n >= 1000) return (n / 1000).toFixed(1) + 'K'
    return n.toString()
  }

  function ctrColor(ctr) {
    if (ctr >= 4) return '#10b981'
    if (ctr >= 2) return '#f59e0b'
    return '#ef4444'
  }

  function ctrBadge(ctr) {
    if (ctr >= 4) return '🟢'
    if (ctr >= 2) return '🟡'
    return '🔴'
  }
</script>

<div class="app">
  <!-- Sidebar -->
  <aside class="sidebar">
    <div class="brand">
      <div class="logo">JA</div>
      <div>
        <div class="brand-text">JB APUL</div>
        <div class="brand-sub">Analytics</div>
      </div>
    </div>

    <!-- Channel Selector -->
    <div class="channel-select">
      <label>Channel</label>
      {#if loading.channels}
        <div class="loading-sm">Loading...</div>
      {:else}
        <select bind:value={selectedChannelId}>
          <option value={null}>Pilih Channel</option>
          {#each channels as ch}
            <option value={ch.id}>{ch.name}</option>
          {/each}
        </select>
      {/if}
    </div>

    <!-- Nav -->
    {#if selectedChannelId}
      <nav class="nav">
        <button class:active={activeTab === 'overview'} on:click={() => activeTab = 'overview'}>
          📊 Overview
        </button>
        <button class:active={activeTab === 'performance'} on:click={() => activeTab = 'performance'}>
          🎯 Video Performance
        </button>
        <button class:active={activeTab === 'intelligence'} on:click={() => activeTab = 'intelligence'}>
          🧠 Content Intelligence
        </button>
        <button class:active={activeTab === 'titles'} on:click={() => activeTab = 'titles'}>
          ✍️ Title Generator
        </button>
      </nav>
    {/if}
  </aside>

  <!-- Main -->
  <main class="main">
    {#if error}
      <div class="error-banner">
        ⚠️ {error}
        <button on:click={() => error = null}>✕</button>
      </div>
    {/if}

    {#if !selectedChannelId}
      <div class="empty-state">
        <div class="empty-icon">📊</div>
        <h2>Pilih Channel</h2>
        <p>Pilih channel dari sidebar untuk melihat analytics</p>
      </div>
    {:else}
      <!-- Channel Header -->
      <header class="channel-header">
        <div>
          <h1>{selectedChannel?.name || 'Channel'}</h1>
          <span class="channel-stats">
            {formatNumber(selectedChannel?.subscriber_count)} subs • 
            {formatNumber(selectedChannel?.total_views)} views • 
            {selectedChannel?.video_count || 0} videos
          </span>
        </div>
        <button class="btn-snapshot" on:click={takeSnapshot} disabled={loading.performance}>
          {loading.performance ? '⏳ Loading...' : '📸 Snapshot'}
        </button>
      </header>

      <!-- Tab Content -->
      {#if activeTab === 'overview'}
        <!-- Overview Cards -->
        <div class="cards">
          {#if loading.analytics}
            <div class="card skeleton">Loading analytics...</div>
          {:else if analytics?.summary}
            <div class="card">
              <div class="card-label">Views (30d)</div>
              <div class="card-value">{formatNumber(analytics.summary.total_views)}</div>
            </div>
            <div class="card">
              <div class="card-label">Watch Hours</div>
              <div class="card-value">{analytics.summary.total_watch_hours}h</div>
            </div>
            <div class="card">
              <div class="card-label">Avg CTR</div>
              <div class="card-value" style="color: {ctrColor(analytics.summary.avg_ctr)}">
                {analytics.summary.avg_ctr}%
              </div>
            </div>
            <div class="card">
              <div class="card-label">Net Subs</div>
              <div class="card-value" style="color: {analytics.summary.net_subs >= 0 ? '#10b981' : '#ef4444'}">
                {analytics.summary.net_subs > 0 ? '+' : ''}{analytics.summary.net_subs}
              </div>
            </div>
            <div class="card">
              <div class="card-label">Impressions</div>
              <div class="card-value">{formatNumber(analytics.summary.total_impressions)}</div>
            </div>
            <div class="card">
              <div class="card-label">Avg View %</div>
              <div class="card-value">{analytics.summary.avg_view_percentage}%</div>
            </div>
          {:else}
            <div class="card">No analytics data. Check channel connection.</div>
          {/if}
        </div>

        <!-- Quick Intelligence Preview -->
        {#if intelligence?.success}
          <div class="section">
            <h2>🧠 Quick Insights</h2>
            <div class="insights-grid">
              <div class="insight-card good">
                <div class="insight-label">High-CTR Videos</div>
                <div class="insight-value">{intelligence.high_ctr.avg_ctr}%</div>
                <div class="insight-detail">{intelligence.high_ctr.count} videos • avg {formatNumber(intelligence.high_ctr.avg_views)} views</div>
              </div>
              <div class="insight-card bad">
                <div class="insight-label">Low-CTR Videos</div>
                <div class="insight-value">{intelligence.low_ctr.avg_ctr}%</div>
                <div class="insight-detail">{intelligence.low_ctr.count} videos • avg {formatNumber(intelligence.low_ctr.avg_views)} views</div>
              </div>
            </div>
            {#if intelligence.recommendations?.length > 0}
              <div class="recommendations">
                {#each intelligence.recommendations as rec}
                  <div class="rec-item">💡 {rec}</div>
                {/each}
              </div>
            {/if}
          </div>
        {/if}

      {:else if activeTab === 'performance'}
        <!-- Video Performance Table -->
        <div class="section">
          <div class="section-header">
            <h2>🎯 Video Performance</h2>
            <span class="badge">{performance.length} videos</span>
          </div>

          {#if loading.performance}
            <div class="loading">Loading...</div>
          {:else if performance.length > 0}
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Video</th>
                    <th>CTR</th>
                    <th>Views</th>
                    <th>Impressions</th>
                    <th>Watch Min</th>
                    <th>Avg View %</th>
                  </tr>
                </thead>
                <tbody>
                  {#each performance as v}
                    <tr>
                      <td class="video-cell">
                        {#if v.thumbnail_url}
                          <img src={v.thumbnail_url} alt="" class="thumb" />
                        {/if}
                        <span class="video-title">{v.title || v.video_id}</span>
                      </td>
                      <td>
                        <span class="ctr-badge">{ctrBadge(v.ctr)}</span>
                        <span style="color: {ctrColor(v.ctr)}; font-weight: 600;">{v.ctr}%</span>
                      </td>
                      <td>{formatNumber(v.views)}</td>
                      <td>{formatNumber(v.impressions)}</td>
                      <td>{Math.round(v.watch_minutes || 0)}</td>
                      <td>{Math.round(v.avg_view_percentage || 0)}%</td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          {:else}
            <div class="empty">No data. Click Snapshot to fetch.</div>
          {/if}
        </div>

      {:else if activeTab === 'intelligence'}
        <!-- Content Intelligence -->
        <div class="section">
          <h2>🧠 Content Intelligence</h2>

          {#if loading.intelligence}
            <div class="loading">Analyzing patterns...</div>
          {:else if intelligence?.success}
            <div class="intel-grid">
              <!-- High CTR -->
              <div class="intel-card good">
                <h3>🏆 What's Working (High CTR)</h3>
                <div class="intel-stat">
                  <span class="big">{intelligence.high_ctr.avg_ctr}%</span>
                  <span class="label">avg CTR</span>
                </div>
                <div class="intel-stat">
                  <span class="big">{formatNumber(intelligence.high_ctr.avg_views)}</span>
                  <span class="label">avg views</span>
                </div>
                <h4>Top Keywords</h4>
                <div class="keywords">
                  {#each intelligence.high_ctr.patterns.top_keywords.slice(0, 8) as [word, count]}
                    <span class="keyword good">{word} ({count})</span>
                  {/each}
                </div>
                <h4>Sample Titles</h4>
                <ul class="title-list">
                  {#each intelligence.high_ctr.patterns.sample_titles as title}
                    <li>{title}</li>
                  {/each}
                </ul>
              </div>

              <!-- Low CTR -->
              <div class="intel-card bad">
                <h3>⚠️ What's Not Working (Low CTR)</h3>
                <div class="intel-stat">
                  <span class="big">{intelligence.low_ctr.avg_ctr}%</span>
                  <span class="label">avg CTR</span>
                </div>
                <div class="intel-stat">
                  <span class="big">{formatNumber(intelligence.low_ctr.avg_views)}</span>
                  <span class="label">avg views</span>
                </div>
                <h4>Common Keywords</h4>
                <div class="keywords">
                  {#each intelligence.low_ctr.patterns.top_keywords.slice(0, 8) as [word, count]}
                    <span class="keyword bad">{word} ({count})</span>
                  {/each}
                </div>
                <h4>Sample Titles</h4>
                <ul class="title-list">
                  {#each intelligence.low_ctr.patterns.sample_titles as title}
                    <li>{title}</li>
                  {/each}
                </ul>
              </div>
            </div>

            <!-- Recommendations -->
            {#if intelligence.recommendations?.length > 0}
              <div class="rec-section">
                <h3>💡 Rekomendasi</h3>
                {#each intelligence.recommendations as rec}
                  <div class="rec-card">{rec}</div>
                {/each}
              </div>
            {/if}
          {:else}
            <div class="empty">No data. Run Snapshot first.</div>
          {/if}
        </div>

      {:else if activeTab === 'titles'}
        <!-- Title Generator -->
        <div class="section">
          <h2>✍️ Smart Title Generator</h2>
          <p class="subtitle">Generate title berdasarkan pattern dari video high-CTR kamu</p>

          <div class="title-form">
            <input 
              type="text" 
              bind:value={titleTopic} 
              placeholder="Topic (e.g., whale sounds, ocean waves)"
              on:keydown={(e) => e.key === 'Enter' && suggestTitles()}
            />
            <button class="btn-primary" on:click={suggestTitles} disabled={loading.titles || !titleTopic.trim()}>
              {loading.titles ? '⏳ Generating...' : '✨ Generate Titles'}
            </button>
          </div>

          {#if titleSuggestions.length > 0}
            <div class="suggestions">
              {#each titleSuggestions as s, i}
                <div class="suggestion-card">
                  <div class="suggestion-num">{i + 1}</div>
                  <div class="suggestion-content">
                    <div class="suggestion-title">{s.title}</div>
                    {#if s.reason}
                      <div class="suggestion-reason">{s.reason}</div>
                    {/if}
                  </div>
                </div>
              {/each}
            </div>
          {/if}
        </div>
      {/if}
    {/if}
  </main>
</div>

<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }

  .app { display: flex; min-height: 100vh; font-family: 'Inter', -apple-system, sans-serif; background: #f8fafc; }

  /* Sidebar */
  .sidebar { width: 260px; background: #0f172a; color: #e2e8f0; padding: 0; position: fixed; height: 100vh; overflow-y: auto; }
  .brand { display: flex; align-items: center; gap: 12px; padding: 24px 20px; border-bottom: 1px solid rgba(255,255,255,.06); }
  .logo { width: 40px; height: 40px; border-radius: 10px; background: linear-gradient(135deg, #6366f1, #8b5cf6); display: grid; place-items: center; font-weight: 800; font-size: 13px; color: #fff; }
  .brand-text { font-size: 15px; font-weight: 800; }
  .brand-sub { font-size: 10px; color: #64748b; text-transform: uppercase; letter-spacing: .05em; }

  .channel-select { padding: 16px 20px; border-bottom: 1px solid rgba(255,255,255,.06); }
  .channel-select label { font-size: 11px; color: #64748b; text-transform: uppercase; font-weight: 600; letter-spacing: .05em; display: block; margin-bottom: 8px; }
  .channel-select select { width: 100%; padding: 8px 10px; border-radius: 8px; border: 1px solid #334155; background: #1e293b; color: #e2e8f0; font-size: 13px; }
  .loading-sm { color: #64748b; font-size: 12px; }

  .nav { padding: 12px 12px; display: flex; flex-direction: column; gap: 2px; }
  .nav button { display: flex; align-items: center; gap: 10px; padding: 10px 14px; border: none; background: transparent; color: #94a3b8; font-size: 13px; font-weight: 600; border-radius: 8px; cursor: pointer; text-align: left; transition: all .15s; }
  .nav button:hover { background: rgba(255,255,255,.06); color: #e2e8f0; }
  .nav button.active { background: rgba(99,102,241,.15); color: #a5b4fc; }

  /* Main */
  .main { flex: 1; margin-left: 260px; padding: 0; }

  .error-banner { background: #fef2f2; border-bottom: 1px solid #fecaca; color: #991b1b; padding: 12px 24px; display: flex; justify-content: space-between; align-items: center; font-size: 13px; }
  .error-banner button { background: none; border: none; cursor: pointer; font-size: 16px; }

  .empty-state { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 60vh; color: #64748b; }
  .empty-icon { font-size: 48px; margin-bottom: 16px; }
  .empty-state h2 { color: #1e293b; margin-bottom: 8px; }

  .channel-header { display: flex; justify-content: space-between; align-items: center; padding: 24px 32px; background: #fff; border-bottom: 1px solid #e2e8f0; }
  .channel-header h1 { font-size: 20px; font-weight: 700; color: #0f172a; }
  .channel-stats { font-size: 13px; color: #64748b; }
  .btn-snapshot { padding: 8px 16px; border-radius: 8px; border: 1px solid #e2e8f0; background: #fff; font-size: 13px; font-weight: 600; cursor: pointer; transition: all .15s; }
  .btn-snapshot:hover { background: #f1f5f9; }
  .btn-snapshot:disabled { opacity: .5; cursor: not-allowed; }

  /* Cards */
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 16px; padding: 24px 32px; }
  .card { background: #fff; border-radius: 12px; padding: 20px; border: 1px solid #e2e8f0; }
  .card-label { font-size: 12px; color: #64748b; font-weight: 600; text-transform: uppercase; letter-spacing: .03em; margin-bottom: 8px; }
  .card-value { font-size: 28px; font-weight: 800; color: #0f172a; }
  .skeleton { color: #94a3b8; font-size: 13px; }

  /* Section */
  .section { padding: 24px 32px; }
  .section h2 { font-size: 18px; font-weight: 700; color: #0f172a; margin-bottom: 16px; }
  .section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
  .badge { background: #f1f5f9; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 600; color: #64748b; }
  .subtitle { color: #64748b; font-size: 14px; margin-bottom: 20px; }

  /* Insights */
  .insights-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }
  .insight-card { padding: 20px; border-radius: 12px; border: 1px solid; }
  .insight-card.good { background: #f0fdf4; border-color: #bbf7d0; }
  .insight-card.bad { background: #fef2f2; border-color: #fecaca; }
  .insight-label { font-size: 12px; font-weight: 600; text-transform: uppercase; color: #64748b; margin-bottom: 8px; }
  .insight-value { font-size: 32px; font-weight: 800; }
  .insight-card.good .insight-value { color: #16a34a; }
  .insight-card.bad .insight-value { color: #dc2626; }
  .insight-detail { font-size: 12px; color: #64748b; margin-top: 4px; }

  .recommendations { display: flex; flex-direction: column; gap: 8px; }
  .rec-item { background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: 12px 16px; font-size: 13px; color: #92400e; }

  /* Table */
  .table-wrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 12px; overflow: hidden; border: 1px solid #e2e8f0; }
  thead th { background: #f8fafc; padding: 12px 16px; font-size: 12px; font-weight: 600; color: #64748b; text-transform: uppercase; text-align: left; border-bottom: 1px solid #e2e8f0; }
  tbody td { padding: 12px 16px; font-size: 13px; border-bottom: 1px solid #f1f5f9; }
  tbody tr:hover { background: #f8fafc; }
  .video-cell { display: flex; align-items: center; gap: 10px; max-width: 300px; }
  .thumb { width: 48px; height: 36px; object-fit: cover; border-radius: 4px; }
  .video-title { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 200px; }
  .ctr-badge { margin-right: 4px; }

  /* Intelligence */
  .intel-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 24px; }
  .intel-card { padding: 24px; border-radius: 12px; border: 1px solid; }
  .intel-card.good { background: #f0fdf4; border-color: #bbf7d0; }
  .intel-card.bad { background: #fef2f2; border-color: #fecaca; }
  .intel-card h3 { font-size: 15px; margin-bottom: 16px; }
  .intel-stat { display: flex; align-items: baseline; gap: 8px; margin-bottom: 8px; }
  .intel-stat .big { font-size: 28px; font-weight: 800; }
  .intel-card.good .big { color: #16a34a; }
  .intel-card.bad .big { color: #dc2626; }
  .intel-stat .label { font-size: 12px; color: #64748b; }
  .intel-card h4 { font-size: 12px; color: #64748b; text-transform: uppercase; margin: 16px 0 8px; }
  .keywords { display: flex; flex-wrap: wrap; gap: 6px; }
  .keyword { padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
  .keyword.good { background: #dcfce7; color: #166534; }
  .keyword.bad { background: #fee2e2; color: #991b1b; }
  .title-list { list-style: none; }
  .title-list li { font-size: 12px; color: #475569; padding: 4px 0; border-bottom: 1px solid rgba(0,0,0,.05); }

  .rec-section { margin-top: 24px; }
  .rec-section h3 { font-size: 15px; margin-bottom: 12px; }
  .rec-card { background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: 14px 18px; font-size: 13px; color: #92400e; margin-bottom: 8px; }

  /* Title Generator */
  .title-form { display: flex; gap: 12px; margin-bottom: 24px; }
  .title-form input { flex: 1; padding: 10px 14px; border: 1px solid #e2e8f0; border-radius: 8px; font-size: 14px; }
  .title-form input:focus { outline: none; border-color: #6366f1; box-shadow: 0 0 0 3px rgba(99,102,241,.1); }
  .btn-primary { padding: 10px 20px; background: #6366f1; color: #fff; border: none; border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer; transition: all .15s; }
  .btn-primary:hover { background: #4f46e5; }
  .btn-primary:disabled { opacity: .5; cursor: not-allowed; }

  .suggestions { display: flex; flex-direction: column; gap: 12px; }
  .suggestion-card { display: flex; gap: 16px; background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px 20px; transition: all .15s; }
  .suggestion-card:hover { border-color: #6366f1; box-shadow: 0 2px 8px rgba(99,102,241,.1); }
  .suggestion-num { width: 32px; height: 32px; border-radius: 8px; background: #f1f5f9; display: grid; place-items: center; font-weight: 700; font-size: 14px; color: #6366f1; flex-shrink: 0; }
  .suggestion-title { font-size: 14px; font-weight: 600; color: #0f172a; margin-bottom: 4px; }
  .suggestion-reason { font-size: 12px; color: #64748b; }

  .loading { color: #94a3b8; font-size: 14px; padding: 20px 0; }
  .empty { color: #94a3b8; font-size: 14px; padding: 40px 0; text-align: center; }
</style>
