# PRD: YouTube Growth Intelligence System — JB APUL v3

**Created:** 2026-08-03
**Status:** Phase 1 — Not Started
**Owner:** Jay Bani
**Server:** deploy@137.184.48.104 — /var/www/jb_apulv3
**Stack:** FastAPI + PostgreSQL + Redis + Docker Compose

---

## 1. Problem Statement

8 YouTube channels (underwater/relaxation niche), beberapa ditolak monet "reused content". Upload 248+ video tapi growth lambat. Root cause:

- **Tidak ada data CTR** → tidak tahu video mana yang thumbnail/title-nya works
- **Dashboard banyak cosmetics, sedikit substance** — CTR random number, AI Score random, Trend random
- **Loop PRODUCE → UPLOAD ada, tapi MEASURE → LEARN → IMPROVE tidak ada**
- **Setiap upload = tebak style** → tidak belajar dari video yang berhasil

## 2. Goal

Bikin sistem yang:
1. Tarik data real dari YouTube Analytics (terutama CTR)
2. Identifikasi video mana yang perform (dan kenapa)
3. Rekomendasi style thumbnail + title untuk video berikutnya berdasarkan data
4. Track improvement dari waktu ke waktu

**Success metric:** CTR rata-rata channel naik dari ~2% ke 4%+ dalam 2 bulan.

---

## 3. Current State — Channel Data (2026-08-03)

| Channel | ID | YouTube ID | Token | Views (30d) | Watch Hours | Avg View % | Net Subs |
|---|---|---|---|---|---|---|---|
| Pure Harmony | 1 | UCubgYk6uWdmnfUrxwOQ-q9g | ✅ | 1,750 | 581.9h | 7.5% | +1 |
| NUVORA | 2 | UCZIJ0zK1jiC4TvhK2-KVNDw | ✅ | 724 | 264.0h | 14.6% | +1 |
| Healing Aura Lab | 3 | UCX80T-trXhMkECzjt_OcsQQ | ✅ | 834 | 226.0h | 11.3% | +5 |

**Key insight:** NUVORA retention 2x lebih baik dari Pure Harmony tapi views paling rendah → kemungkinan besar masalah CTR (konten bagus, tapi tidak diklik).

---

## 4. Current Architecture

### Backend
- `backend/app/api/ai.py` — AI analysis endpoint
- `backend/app/api/youtube_api.py` — YouTube Data API + Analytics API
- `backend/app/api/channels.py` — Channel CRUD
- `backend/app/api/production.py` — Production jobs
- `backend/app/api/uploads.py` — Upload + metadata pool
- `backend/app/api/metadata.py` — Metadata CRUD
- `backend/app/main.py` — FastAPI app, routers

### Workers
- `workers/production/worker.py` — Orchestrator (3 pipelines)
- `workers/upload/worker.py` — YouTube upload + thumbnail pick
- `workers/livestream/worker.py` — Livestream management

### Frontend
- `backend/templates/dashboard.html` — Main dashboard (Alpine.js + Tailwind)
- `backend/templates/production.html` — Production UI (3 tabs)
- `backend/templates/media.html` — Media + metadata tabs
- `backend/templates/uploads.html` — Upload management

### Database
- PostgreSQL (port 5433 → 5432 container)
- User: `jb_user` / Password: `change-me` / DB: `jb_apulv3`

### AI Provider
- 9router — `https://router.wflabs.dev/v1`
- Model: `wf/mimo-mimo-v2.5-pro`

### SSH Access
```bash
ssh deploy@137.184.48.104
cd /var/www/jb_apulv3
docker compose restart backend
docker compose up -d --build worker-production
git push origin master  # ONLY when explicitly told
```

---

## 5. What Currently Works vs What's Broken

### Works ✅
- 3 production pipelines (final/static/dynamic)
- YouTube upload via Google API
- Metadata pool + 40-day rotation
- AI detect: `bad_title`, `low_engagement`, `dead_video`
- Apply fix langsung ke YouTube (title/desc/tags)
- Channel analytics (views, watch time, subs per day)
- Multi-channel management

### Broken / Fake ❌
- **CTR di dashboard = random number** — `Math.random() * 4 + 1`
- **AI Score = random** — `Math.floor(Math.random() * 40 + 50)`
- **Trend = random** — `Math.random() > 0.5 ? 'up' : 'flat'`
- **`/api/channels` PUT 500 error** — datetime serialization bug di `ChannelResponse` model

### Missing ❌
- Per-video CTR data dari YouTube Analytics
- Impressions data
- Video ranking by performance
- Low CTR detection
- Thumbnail style analysis
- Upload time optimization
- Content recommendation engine

---

## 6. PRD — Phase 1: Data Foundation

### 6.1 Add CTR + Impressions to YouTube Analytics

**File:** `backend/app/api/youtube_api.py`

**What to change:**
- Channel analytics query (line ~36): tambah metrics `impressions,impressionClickThroughRate`
- Top videos analytics query (line ~46): tambah metrics `impressions,impressionClickThroughRate`

```python
# Current:
metrics="views,estimatedMinutesWatched,subscribersGained,subscribersLost,averageViewDuration,averageViewPercentage"

# New:
metrics="views,estimatedMinutesWatched,subscribersGained,subscribersLost,averageViewDuration,averageViewPercentage,impressions,impressionClickThroughRate"
```

```python
# Current top videos:
metrics="views,estimatedMinutesWatched,averageViewPercentage,subscribersGained"

# New top videos:
metrics="views,estimatedMinutesWatched,averageViewPercentage,subscribersGained,impressions,impressionClickThroughRate"
```

**Verify:** `GET /api/youtube/analytics/1` returns `impressions` and `impressionClickThroughRate` in response.

### 6.2 Create video_analytics Table

**New file:** `backend/app/models/video_analytics.py`

```python
class VideoAnalytics(Base):
    __tablename__ = "video_analytics"
    
    id = Column(Integer, primary_key=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False)
    video_id = Column(String, nullable=False)  # YouTube video ID
    video_title = Column(String)
    thumbnail_url = Column(String)
    
    # Metrics snapshot
    snapshot_date = Column(Date, nullable=False)
    impressions = Column(Integer, default=0)
    ctr = Column(Float, default=0.0)  # impressionClickThroughRate
    views = Column(Integer, default=0)
    watch_minutes = Column(Float, default=0.0)
    avg_view_percentage = Column(Float, default=0.0)
    likes = Column(Integer, default=0)
    subs_gained = Column(Integer, default=0)
    
    # Computed
    created_at = Column(DateTime, default=func.now())
    
    # Unique constraint: one snapshot per video per day
    __table_args__ = (
        UniqueConstraint('video_id', 'snapshot_date', name='uq_video_snapshot'),
    )
```

**Verify:** Table created on backend restart (auto via `Base.metadata.create_all`).

### 6.3 New Endpoint: Fetch + Store Per-Video Analytics

**File:** `backend/app/api/youtube_api.py`

**New endpoint:** `POST /api/youtube/snapshot/{channel_id}`

Logic:
1. Call YouTube Analytics API — per-video metrics with CTR + impressions
2. For each video: upsert into `video_analytics` table (video_id + today's date)
3. Return summary: total videos, avg CTR, top 3 by CTR, bottom 3 by CTR

**Verify:** `POST /api/youtube/snapshot/1` creates records in `video_analytics` table.

### 6.4 New Endpoint: Video Performance Ranking

**File:** `backend/app/api/youtube_api.py`

**New endpoint:** `GET /api/youtube/performance/{channel_id}`

Query params: `?days=30&sort=ctr&order=desc&limit=20`

Logic:
1. Read latest snapshot from `video_analytics` for each video
2. Sort by CTR (or views, impressions, watch_minutes)
3. Return ranked list with: video_id, title, thumbnail_url, impressions, ctr, views

**Verify:** `GET /api/youtube/performance/1?sort=ctr` returns videos sorted by CTR.

### 6.5 Dashboard: Video Performance Panel

**File:** `backend/templates/dashboard.html`

Add new section below AI Analysis panel:

**"📊 Video Performance" panel:**
- Tab: "Top Performers" / "Needs Attention"
- Top tab: 5 videos with highest CTR → show thumbnail preview, title, CTR%, impressions, views
- Bottom tab: 5 videos with lowest CTR (< 2%) → same format, red highlight
- Button: "📸 Take Snapshot" → calls `POST /api/youtube/snapshot/{channel_id}`
- Auto-load latest snapshot on channel select

**Design:**
```
┌─────────────────────────────────────────────┐
│ 📊 Video Performance          [📸 Snapshot] │
│ ┌───────────┬──────────────┐                │
│ │ Top CTR   │ Needs Fix    │                │
│ └───────────┴──────────────┘                │
│                                             │
│ ┌──────┐ Title: "10 Hours Ocean Waves"      │
│ │thumb │ CTR: 8.5% | Imp: 15,000 | Views:1,275│
│ └──────┘ Published: 2026-07-15              │
│                                             │
│ ┌──────┐ Title: "Deep Sea Meditation"       │
│ │thumb │ CTR: 6.2% | Imp: 12,000 | Views: 744│
│ └──────┘ Published: 2026-07-20              │
└─────────────────────────────────────────────┘
```

**Verify:** Dashboard shows real video thumbnails ranked by CTR after taking snapshot.

### 6.6 Fix Channel Stats (Remove Fake Data)

**File:** `backend/templates/dashboard.html`

Remove random generators:
```javascript
// REMOVE:
ctr: ch.ctr || (Math.random() * 4 + 1).toFixed(1),
aiScore: ch.aiScore || Math.floor(Math.random() * 40 + 50),
trend: ch.trend || (Math.random() > 0.5 ? 'up' : 'flat'),

// REPLACE WITH: real data from API (or show "-" when no data)
ctr: ch.ctr || '-',
aiScore: ch.aiScore || '-',
trend: ch.trend || '-',
```

Also fix `ChannelResponse` model datetime serialization bug (causes 500 on PUT /api/channels).

**Verify:** Dashboard shows "-" instead of random numbers when data not available.

---

## 7. PRD — Phase 2: Pattern Recognition

### 7.1 High-CTR Pattern Analysis

**File:** `backend/app/api/ai.py`

**New endpoint:** `POST /api/ai/analyze-patterns/{channel_id}`

Logic:
1. Read video_analytics for channel — get top 5 by CTR
2. For each top video: fetch video details (title, description, tags, thumbnail URL)
3. Send to AI: "Analyze these high-CTR videos. What patterns do you see in: title format, keywords, description structure, thumbnail style?"
4. Return: pattern summary + recommendations

**AI Prompt template:**
```
Analyze these YouTube videos with the highest click-through rates:

Video 1: "{title}" — CTR: {ctr}%, Impressions: {impressions}, Views: {views}
Title: {title}
Description: {description}
Tags: {tags}
Thumbnail: {thumbnail_url}

[repeat for each video]

Identify patterns in:
1. Title format (length, keywords, structure, numbers, emotional triggers)
2. Description style (length, keywords, call-to-action)
3. Tags strategy (count, relevance, niche terms)

Give me a concrete template I can use for my next video.
```

**Verify:** Response contains specific, actionable patterns.

### 7.2 Low-CTR Alert in AI Analysis

**File:** `backend/app/api/ai.py` — in `analyze_channel()` function

Add new issue type detection:
```python
# After existing detections (bad_title, low_engagement, dead_video):

# Detect low CTR (from video_analytics table)
low_ctr_videos = await db.execute(text(
    """SELECT video_id, video_title, ctr, impressions, thumbnail_url 
       FROM video_analytics 
       WHERE channel_id = :cid 
       AND snapshot_date = (SELECT MAX(snapshot_date) FROM video_analytics WHERE channel_id = :cid)
       AND ctr < 2.0 
       AND impressions > 100
       ORDER BY ctr ASC
       LIMIT 5"""
), {"cid": channel_id})

for vid in low_ctr_videos:
    new_issues.append({
        "filename": vid.video_id,
        "issue_type": "low_ctr",
        "severity": "high",
        "description": f"Video '{vid.video_title[:40]}' has CTR {vid.ctr}% on {vid.impressions} impressions — thumbnail/title needs improvement",
    })
```

**Verify:** AI Analysis shows "low_ctr" issues for videos with CTR < 2%.

### 7.3 Dashboard: Pattern Insights Panel

**File:** `backend/templates/dashboard.html`

Add section: "🧠 Content Intelligence"

```
┌─────────────────────────────────────────────┐
│ 🧠 Content Intelligence                     │
│                                             │
│ 🏆 What's Working (High CTR Videos)         │
│ • Title style: "X Hours [Nature Sound]"     │
│ • Keywords: relaxing, sleep, meditation     │
│ • Avg CTR: 6.8%                             │
│                                             │
│ ⚠️ What's Not Working (Low CTR Videos)      │
│ • Title style: short, no keywords           │
│ • Common issue: generic titles              │
│ • Avg CTR: 1.1%                             │
│                                             │
│ 💡 Recommendations for Next Upload          │
│ 1. Use format: "[Duration] [Sound] for     │
│    [Purpose]" — proven CTR 5%+              │
│ 2. Include "relaxing" or "sleep" in title   │
│ 3. Blue-themed thumbnails perform 2x better │
│    than green                               │
│                                             │
│ [🔄 Refresh Analysis]                       │
└─────────────────────────────────────────────┘
```

**Verify:** Panel shows real analysis from AI based on actual CTR data.

---

## 8. PRD — Phase 3: Actionable Improvements

### 8.1 Smart Title Generator

**File:** `backend/app/api/ai.py`

**New endpoint:** `POST /api/ai/suggest-titles`

Request body:
```json
{
    "channel_id": 1,
    "topic": "whale sounds",
    "count": 5
}
```

Logic:
1. Fetch high-CTR patterns from previous analysis
2. Fetch metadata pool titles for this channel
3. AI prompt: "Generate {count} YouTube titles for a {niche} channel about '{topic}'. Follow these proven patterns from my best-performing videos: {patterns}. Each title should be SEO-friendly and optimized for click-through rate."
4. Return: 5 suggested titles with SEO score

**Verify:** Titles follow patterns from high-CTR videos, not generic.

### 8.2 Best Upload Time Analysis

**File:** `backend/app/api/youtube_api.py`

**New endpoint:** `GET /api/youtube/best-time/{channel_id}`

Logic:
1. Fetch daily analytics for channel (30-90 days)
2. Correlate upload day/time with first-24h views
3. Return: best day, best hour, heatmap data

**Verify:** Returns specific recommendation like "Upload Tuesday 8PM WIB".

### 8.3 Dashboard: Quick Actions from Analysis

In AI Analysis panel, for each `low_ctr` issue:

```
┌─────────────────────────────────────────────┐
│ 🔴 Video "Deep Sea Relaxation" — CTR 1.2%   │
│ Published: 2026-07-10 | Impressions: 8,500  │
│                                             │
│ [📷 Current Thumbnail]                      │
│                                             │
│ 💡 Suggested Fixes:                         │
│ 1. Change title to: "10 Hours Deep Sea      │
│    Sounds for Sleep & Meditation"           │
│    (matches high-CTR pattern)               │
│ 2. Upload new thumbnail with:               │
│    • Deep blue color scheme                 │
│    • Text overlay "RELAXING SLEEP"          │
│    • Centered fish/coral image              │
│                                             │
│ [Apply Title] [Skip] [View on YouTube]      │
└─────────────────────────────────────────────┘
```

---

## 9. PRD — Phase 4: Automation (Future)

- Auto A/B test title changes → track CTR before/after
- Auto thumbnail replacement when CTR drops below threshold
- Content calendar AI → plan next week's uploads based on analytics
- Revenue optimization → identify high-RPM video types
- Cross-channel insights → why does channel X outperform Y?

---

## 10. Technical Notes

### YouTube Analytics API — Available Metrics

```
# Channel-level:
views, estimatedMinutesWatched, subscribersGained, subscribersLost,
averageViewDuration, averageViewPercentage,
impressions, impressionClickThroughRate

# Per-video:
views, estimatedMinutesWatched, averageViewPercentage,
subscribersGained, impressions, impressionClickThroughRate

# Revenue (requires monetization):
estimatedRevenue, estimatedAdRevenue, estimatedRedPartnerRevenue,
cpm, playbackBasedCpm
```

### CTR Calculation
- YouTube provides `impressionClickThroughRate` directly (percentage)
- Formula: CTR = (views / impressions) × 100
- Good CTR: 4-10% | Average: 2-4% | Low: < 2%
- Note: CTR varies by impression source (browse, search, suggested)

### Current Fake Data to Remove
```javascript
// dashboard.html line 383
ctr: ch.ctr || (Math.random() * 4 + 1).toFixed(1),
aiScore: ch.aiScore || Math.floor(Math.random() * 40 + 50),
trend: ch.trend || (Math.random() > 0.5 ? 'up' : 'flat'),
```

### Known Bugs to Fix
- `PUT /api/channels/{id}` returns 500 — datetime serialization in `ChannelResponse`
- `undoFix()` was accidentally deleted (fixed in commit 48aa5c5)

---

## 11. Implementation Order

### Week 1: Data Collection (Phase 1)
- [ ] 1.1 Add CTR + impressions to YouTube Analytics query
- [ ] 1.2 Create `video_analytics` table
- [ ] 1.3 Build `POST /api/youtube/snapshot/{channel_id}` endpoint
- [ ] 1.4 Build `GET /api/youtube/performance/{channel_id}` endpoint
- [ ] 1.5 Build Video Performance panel in dashboard
- [ ] 1.6 Remove fake data (random CTR, AI Score, Trend)
- [ ] 1.7 Fix ChannelResponse datetime bug

### Week 2: Pattern Recognition (Phase 2)
- [ ] 2.1 Build `POST /api/ai/analyze-patterns/{channel_id}` endpoint
- [ ] 2.2 Add `low_ctr` issue type to AI analysis
- [ ] 2.3 Build Content Intelligence panel in dashboard

### Week 3: Actionable (Phase 3)
- [ ] 3.1 Build smart title generator based on high-CTR patterns
- [ ] 3.2 Build best upload time analysis
- [ ] 3.3 Add quick actions for low-CTR issues in dashboard

### Week 4+: Automation (Phase 4)
- [ ] 4.1 Auto A/B testing
- [ ] 4.2 Content calendar
- [ ] 4.3 Revenue optimization

---

## 12. Commit History (Relevant)

```
0f246ad fix: remove thumbnail generation feature
48aa5c5 fix: restore undoFix() function header accidentally deleted
0478b1b fix: dynamic video CPU optimize + batch output + dynamic_status JSON
f66d8e4 fix: seamless progress tracking
94991cd fix: capture FFmpeg errors to DB
d1abb7b fix: custom_dur_seconds + output_filename
ea3d800 feat: metadata CRUD API + metadata tabs UI + production fixes
83ef575 feat: AI-powered analytics dashboard + 9router integration
b884a52 feat: YouTube API integration + AI-powered suggestions
7258d11 feat: AI analysis caching
```

---

## 13. Session Resume Instructions

When resuming this project:
1. Read this PRD file first
2. Check `ssh deploy@137.184.48.104 "cd /var/www/jb_apulv3 && git log --oneline -5"` for latest commits
3. Check `docker compose ps` for container status
4. Check which phase/week is in progress from the checklist above
5. Continue from the last completed item

**DO NOT push to GitHub without explicit user permission.**
