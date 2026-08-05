"""
AI API — JB APUL v3
Settings, analyzer, action engine, fix tracker.
"""

import os
import json
import httpx
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, text
from pydantic import BaseModel
from typing import Optional

from app.db.session import get_db

router = APIRouter()
log = logging.getLogger("ai")

# ── Pydantic Models ──────────────────────────────────────────

class AISettingsUpdate(BaseModel):
    provider: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    save_history: Optional[bool] = None
    skip_fixed: Optional[bool] = None
    auto_detect: Optional[bool] = None
    auto_approve: Optional[bool] = None

class TestConnectionRequest(BaseModel):
    provider: str = "claude"
    base_url: str = ""
    api_key: str = ""
    model: str = ""

class ChatRequest(BaseModel):
    channel_id: int
    message: str

class ApplyFixRequest(BaseModel):
    channel_id: int
    filename: str
    fix_type: str  # 'title' | 'description' | 'tags'
    old_value: str = ""
    new_value: str

class UndoFixRequest(BaseModel):
    fix_id: int

class SkipIssueRequest(BaseModel):
    issue_id: int
    reason: str = ""

# ── Provider Config ───────────────────────────────────────────

PROVIDERS = {
    "9router": {
        "label": "9router (WF Labs)",
        "base_url": "https://router.wflabs.dev/v1",
        "models": ["wf/mimo-mimo-v2.5-pro", "wf/haiku-4.5", "wf/sonnet-4.5", "wf/deepseek-3.2", "wf/glm-5", "wf/deepseek-v4-flash"],
        "needs_key": True,
    },
    "claude": {
        "label": "Claude (Anthropic)",
        "base_url": "https://api.anthropic.com/v1",
        "models": ["claude-haiku-4-5-20251001", "claude-sonnet-4-20250514", "claude-opus-4-20250514"],
        "needs_key": True,
    },
    "openai": {
        "label": "OpenAI (GPT)",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo"],
        "needs_key": True,
    },
    "groq": {
        "label": "Groq (Llama/Mixtral)",
        "base_url": "https://api.groq.com/openai/v1",
        "models": ["llama-3.1-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
        "needs_key": True,
    },
    "custom": {
        "label": "Custom (Ollama/OpenRouter)",
        "base_url": "http://localhost:11434/v1",
        "models": ["llama3", "mistral", "phi3"],
        "needs_key": False,
    },
}

# ── Settings CRUD ─────────────────────────────────────────────

@router.get("/providers")
async def list_providers():
    """List available AI providers and their models."""
    return {"providers": PROVIDERS}


@router.get("/models/{provider}")
async def get_models(provider: str, base_url: str = ""):
    """Get available models for a provider. For 9router/local, fetches live from API."""
    prov = PROVIDERS.get(provider)
    if not prov:
        return {"models": [], "error": "Unknown provider"}

    url = base_url or prov.get("base_url", "")

    # For 9router and custom providers, try to fetch models live
    if provider in ("9router", "custom") and url:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{url}/models")
                if resp.status_code == 200:
                    data = resp.json()
                    models = []
                    for m in data.get("data", []):
                        mid = m.get("id", "")
                        caps = m.get("capabilities", {})
                        models.append({
                            "id": mid,
                            "vision": caps.get("vision", False),
                            "reasoning": caps.get("reasoning", False),
                            "context": caps.get("contextWindow", 0),
                        })
                    return {"models": models, "source": "live"}
        except Exception as e:
            return {"models": [], "error": f"Cannot reach {url}: {e}"}

    return {"models": [{"id": m} for m in prov.get("models", [])], "source": "static"}


@router.get("/settings")
async def get_settings(db: AsyncSession = Depends(get_db)):
    """Get AI settings."""
    result = await db.execute(text("SELECT * FROM ai_settings ORDER BY id LIMIT 1"))
    row = result.mappings().first()
    if not row:
        return {
            "provider": "claude",
            "base_url": "https://api.anthropic.com/v1",
            "api_key": "",
            "model": "claude-haiku-4-5-20251001",
            "save_history": True,
            "skip_fixed": True,
            "auto_detect": False,
            "auto_approve": False,
            "connected": False,
        }
    # Mask API key for display
    data = dict(row)
    if data.get("api_key"):
        key = data["api_key"]
        data["api_key_masked"] = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
        data["api_key_set"] = True
    else:
        data["api_key_masked"] = ""
        data["api_key_set"] = False
    data.pop("api_key", None)
    return data


@router.put("/settings")
async def update_settings(data: AISettingsUpdate, db: AsyncSession = Depends(get_db)):
    """Update AI settings."""
    # Get existing
    result = await db.execute(text("SELECT id FROM ai_settings ORDER BY id LIMIT 1"))
    row = result.first()

    fields = {}
    for k, v in data.model_dump(exclude_unset=True).items():
        if v is not None:
            fields[k] = v

    if not fields:
        return {"success": True, "message": "No changes"}

    if row:
        # Update existing
        set_clauses = []
        values = {}
        for k, v in fields.items():
            set_clauses.append(f"{k} = :{k}")
            values[k] = v
        set_clauses.append("updated_at = NOW()")
        sql = f"UPDATE ai_settings SET {', '.join(set_clauses)} WHERE id = :id"
        values["id"] = row[0]
        await db.execute(text(sql), values)
    else:
        # Insert new
        cols = list(fields.keys())
        placeholders = [f":{k}" for k in cols]
        sql = f"INSERT INTO ai_settings ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"
        await db.execute(text(sql), fields)

    await db.commit()
    return {"success": True, "message": "Settings updated"}


@router.post("/settings/api-key")
async def set_api_key(data: dict, db: AsyncSession = Depends(get_db)):
    """Set or update API key specifically."""
    api_key = data.get("api_key", "")
    if not api_key:
        raise HTTPException(status_code=400, detail="api_key required")

    result = await db.execute(text("SELECT id FROM ai_settings ORDER BY id LIMIT 1"))
    row = result.first()

    if row:
        await db.execute(
            text("UPDATE ai_settings SET api_key = :key, updated_at = NOW() WHERE id = :id"),
            {"key": api_key, "id": row[0]},
        )
    else:
        await db.execute(
            text("INSERT INTO ai_settings (api_key) VALUES (:key)"),
            {"key": api_key},
        )
    await db.commit()
    return {"success": True, "message": "API key saved"}


# ── Test Connection ───────────────────────────────────────────

@router.post("/test-connection")
async def test_connection(data: TestConnectionRequest, db: AsyncSession = Depends(get_db)):
    """Test AI provider connection."""
    provider = data.provider
    base_url = data.base_url
    api_key = data.api_key
    model = data.model

    # Always load saved settings as fallback
    result = await db.execute(text("SELECT * FROM ai_settings ORDER BY id LIMIT 1"))
    settings = result.mappings().first()
    if settings:
        base_url = base_url or settings.get("base_url", "")
        api_key = api_key or settings.get("api_key", "")
        model = model or settings.get("model", "")
        provider = provider or settings.get("provider", "claude")

    if not base_url or not model:
        return {"success": False, "error": "Base URL and model required"}

    # Get provider config
    provider_config = PROVIDERS.get(provider, PROVIDERS["custom"])

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if provider == "claude":
                resp = await client.post(
                    f"{base_url}/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": model,
                        "max_tokens": 50,
                        "messages": [{"role": "user", "content": "Reply with: OK"}],
                    },
                )
            else:
                # OpenAI-compatible
                headers = {"Content-Type": "application/json"}
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"
                resp = await client.post(
                    f"{base_url}/chat/completions",
                    headers=headers,
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": "Reply with: OK"}],
                        "max_tokens": 50,
                        "stream": False,
                    },
                )

            if resp.status_code == 200:
                result = resp.json()
                if provider == "claude":
                    reply = result.get("content", [{}])[0].get("text", "")
                else:
                    reply = result.get("choices", [{}])[0].get("message", {}).get("content", "")

                # Update settings with test result
                await db.execute(text(
                    "UPDATE ai_settings SET last_test_at = NOW(), last_test_status = 'success', last_test_error = NULL WHERE id = (SELECT id FROM ai_settings ORDER BY id LIMIT 1)"
                ))
                await db.commit()

                return {
                    "success": True,
                    "response": reply.strip()[:100],
                    "latency_ms": int(resp.elapsed.total_seconds() * 1000),
                    "model": model,
                    "provider": provider,
                }
            else:
                error = resp.text[:200]
                await db.execute(text(
                    "UPDATE ai_settings SET last_test_at = NOW(), last_test_status = 'failed', last_test_error = :err WHERE id = (SELECT id FROM ai_settings ORDER BY id LIMIT 1)"
                ), {"err": error})
                await db.commit()
                return {"success": False, "error": f"HTTP {resp.status_code}: {error}"}

    except httpx.ConnectError:
        return {"success": False, "error": f"Connection failed: {base_url}"}
    except httpx.TimeoutException:
        return {"success": False, "error": "Connection timeout (30s)"}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


# ── Helper: Generate AI suggestions (BATCH — 1 call for all videos) ──

@router.post("/analyze/{channel_id}")
async def analyze_channel(channel_id: int, db: AsyncSession = Depends(get_db)):
    """Analyze channel with REAL YouTube data — pull from YouTube API first."""
    from app.models.channel import Channel
    from app.models.media import MediaItem
    import httpx

    # Get channel
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    # 1. Pull real data from YouTube API
    yt_videos = []
    yt_analytics = {}
    channel_stats = {}

    if channel.access_token and channel.youtube_channel_id:
        try:
            # Try to get videos via internal API call
            from app.api.youtube_api import _get_youtube_service
            youtube, creds = _get_youtube_service(channel)

            # Get channel stats
            ch_resp = youtube.channels().list(part="statistics", id=channel.youtube_channel_id).execute()
            if ch_resp.get("items"):
                stats = ch_resp["items"][0]["statistics"]
                channel_stats = {
                    "subscribers": int(stats.get("subscriberCount", 0)),
                    "total_views": int(stats.get("viewCount", 0)),
                    "total_videos": int(stats.get("videoCount", 0)),
                }

            # Get videos list
            pl_resp = youtube.channels().list(part="contentDetails", id=channel.youtube_channel_id).execute()
            if pl_resp.get("items"):
                uploads_pid = pl_resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
                pl_items = youtube.playlistItems().list(part="snippet,contentDetails", playlistId=uploads_pid, maxResults=20).execute()
                vid_ids = [i["contentDetails"]["videoId"] for i in pl_items.get("items", [])]

                if vid_ids:
                    vid_resp = youtube.videos().list(part="statistics,snippet", id=",".join(vid_ids)).execute()
                    for v in vid_resp.get("items", []):
                        s = v.get("statistics", {})
                        sn = v.get("snippet", {})
                        yt_videos.append({
                            "video_id": v["id"],
                            "title": sn.get("title", ""),
                            "description": sn.get("description", "")[:200],
                            "tags": sn.get("tags", []),
                            "published_at": sn.get("publishedAt", ""),
                            "view_count": int(s.get("viewCount", 0)),
                            "like_count": int(s.get("likeCount", 0)),
                            "comment_count": int(s.get("commentCount", 0)),
                        })

            # Update token if refreshed
            if creds.token != channel.access_token:
                channel.access_token = creds.token
                await db.commit()

        except Exception as e:
            log.warning(f"YouTube API pull failed: {e}")

    # 2. Load existing fixes (DO NOT repeat)
    fixes_result = await db.execute(text(
        "SELECT filename, fix_type, new_value, applied_at FROM ai_fixes WHERE channel_id = :cid AND status = 'applied' ORDER BY applied_at DESC"
    ), {"cid": channel_id})
    applied_fixes = [dict(r) for r in fixes_result.mappings().all()]

    # 3. Build fixed set
    fixed_set = set()
    for fix in applied_fixes:
        fixed_set.add((fix["filename"], fix["fix_type"]))

    # 4. Detect issues from REAL YouTube data
    new_issues = []
    for vid in yt_videos:
        vid_id = vid["video_id"]
        title = vid["title"]
        views = vid["view_count"]
        likes = vid["like_count"]

        # Already fixed this video's title?
        if (vid_id, "title") in fixed_set:
            continue

        # Detect bad title
        is_bad_title = (
            len(title) < 15
            or title.startswith("final_")
            or title.startswith("UPL")
            or "_" in title
            or title == title.upper()
            or not any(c in title for c in "aeiouAEIOU")  # no vowels = code/filename
        )

        if is_bad_title:
            new_issues.append({
                "filename": vid_id,
                "issue_type": "bad_title",
                "severity": "high",
                "description": f"Title '{title[:50]}' is not SEO-friendly ({views} views)",
            })

        # Detect low engagement
        if views > 10 and likes == 0:
            new_issues.append({
                "filename": vid_id,
                "issue_type": "low_engagement",
                "severity": "medium",
                "description": f"Video '{title[:40]}' has {views} views but 0 likes — poor engagement",
            })

        # Detect dead videos (published > 7 days, < 10 views)
        from datetime import datetime, timedelta, timezone
        try:
            pub_date = datetime.fromisoformat(vid["published_at"].replace("Z", "+00:00"))
            if pub_date < datetime.now(timezone.utc) - timedelta(days=7) and views < 10:
                new_issues.append({
                    "filename": vid_id,
                    "issue_type": "dead_video",
                    "severity": "high",
                    "description": f"Video '{title[:40]}' has only {views} views after 7+ days — needs optimization",
                })
        except:
            pass

    # 5. Save new issues to DB (upsert)
    for issue in new_issues:
        existing = await db.execute(text(
            "SELECT id FROM ai_issues WHERE channel_id = :cid AND filename = :fn AND issue_type = :it AND status = 'open'"
        ), {"cid": channel_id, "fn": issue["filename"], "it": issue["issue_type"]})
        if not existing.first():
            await db.execute(text(
                """INSERT INTO ai_issues (channel_id, filename, issue_type, severity, description, status)
                   VALUES (:cid, :fn, :it, :sev, :desc, 'open')"""
            ), {"cid": channel_id, "fn": issue["filename"], "it": issue["issue_type"], "sev": issue["severity"], "desc": issue["description"]})

    await db.commit()

    # 6. Reload all open issues
    issues_result = await db.execute(text(
        "SELECT * FROM ai_issues WHERE channel_id = :cid AND status = 'open' ORDER BY severity DESC"
    ), {"cid": channel_id})
    all_open = [dict(r) for r in issues_result.mappings().all()]

    # 7. Generate suggestions for open issues using AI + REAL YouTube data
    # Limit to top 5 issues
    top_issues = all_open[:5]

    # No AI suggestions — just use video data

    # Build actions
    actions = []
    for issue in top_issues:
        vid_id = issue["filename"]
        yt_match = next((v for v in yt_videos if v["video_id"] == vid_id), None)
        current_title = yt_match["title"] if yt_match else vid_id
        current_views = yt_match["view_count"] if yt_match else 0

        # Generate recommendation based on issue type
        issue_type = issue["issue_type"]
        if issue_type == "low_engagement":
            rec = "⚠️ Low engagement video. Try new thumbnail or change title format."
        elif issue_type == "bad_title":
            rec = "📝 Title may not match content. Use keywords + emoji for better CTR."
        elif issue_type == "dead_video":
            rec = "💀 Dead video (no views). Consider unlisting or updating with new thumbnail."
        else:
            rec = "🔍 Review this video for potential improvements."
        
        actions.append({
            "issue_id": issue["id"],
            "type": issue["issue_type"],
            "severity": issue["severity"],
            "filename": issue["filename"],
            "current_title": current_title,
            "current_views": current_views,
            "description": issue["description"],
            "recommendation": rec,
        })

    # 10. Update context + cache results
    import json as _json
    cached_data = _json.dumps({
        "actions": actions,
        "fixes_history": applied_fixes[:10],
        "already_fixed": len(applied_fixes),
        "open_issues": len(all_open),
        "channel_name": channel.name,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    })

    await db.execute(text(
        """INSERT INTO ai_context (channel_id, last_analyze_at, total_issues_found, issues_fixed, issues_remaining, last_recommendations, updated_at)
           VALUES (:cid, NOW(), :total, :fixed, :remaining, CAST(:recs AS jsonb), NOW())
           ON CONFLICT (channel_id) DO UPDATE SET
               last_analyze_at = NOW(),
               total_issues_found = :total,
               issues_fixed = :fixed,
               issues_remaining = :remaining,
               last_recommendations = CAST(:recs AS jsonb),
               updated_at = NOW()"""
    ), {
        "cid": channel_id,
        "total": len(applied_fixes) + len(all_open),
        "fixed": len(applied_fixes),
        "remaining": len(all_open),
        "recs": cached_data,
    })
    await db.commit()

    return {
        "success": True,
        "channel": channel.name,
        "channel_id": channel_id,
        "already_fixed": len(applied_fixes),
        "open_issues": len(all_open),
        "actions": actions,
        "fixes_history": applied_fixes[:10],
    }


# ── Load Cached Analysis ─────────────────────────────────────

@router.get("/cached/{channel_id}")
async def get_cached_analysis(channel_id: int, db: AsyncSession = Depends(get_db)):
    """Load last cached analysis for a channel — no AI call needed."""
    ctx_result = await db.execute(text(
        "SELECT last_recommendations, last_analyze_at FROM ai_context WHERE channel_id = :cid"
    ), {"cid": channel_id})
    ctx = ctx_result.mappings().first()

    if not ctx or not ctx.get("last_recommendations"):
        return {"success": False, "message": "No cached analysis. Click Analyze first."}

    import json as _json
    cached = ctx["last_recommendations"]
    if isinstance(cached, str):
        cached = _json.loads(cached)

    # Update fixes_history with current data
    fixes_result = await db.execute(text(
        "SELECT id, filename, fix_type, new_value, status, applied_at FROM ai_fixes WHERE channel_id = :cid ORDER BY applied_at DESC LIMIT 10"
    ), {"cid": channel_id})
    fixes = [dict(r) for r in fixes_result.mappings().all()]

    cached["success"] = True
    cached["cached"] = True
    cached["last_analyze_at"] = str(ctx["last_analyze_at"]) if ctx["last_analyze_at"] else None
    cached["fixes_history"] = fixes

    return cached


# ── Apply Fix ─────────────────────────────────────────────────

@router.post("/apply-fix")
async def apply_fix(data: ApplyFixRequest, db: AsyncSession = Depends(get_db)):
    """Apply a fix and record it in history."""
    # 1. Save to ai_fixes
    result = await db.execute(text(
        """INSERT INTO ai_fixes (channel_id, filename, fix_type, old_value, new_value, status)
           VALUES (:cid, :fn, :ft, :ov, :nv, 'applied')
           RETURNING id"""
    ), {
        "cid": data.channel_id,
        "fn": data.filename,
        "ft": data.fix_type,
        "ov": data.old_value,
        "nv": data.new_value,
    })
    fix_id = result.scalar()

    # 2. Mark issue as fixed
    await db.execute(text(
        """UPDATE ai_issues SET status = 'fixed', fixed_at = NOW(), fix_id = :fid, updated_at = NOW()
           WHERE channel_id = :cid AND filename = :fn AND issue_type = :ft AND status = 'open'"""
    ), {"fid": fix_id, "cid": data.channel_id, "fn": data.filename, "ft": f"bad_{data.fix_type}"})

    # 3. Update context
    await db.execute(text(
        """UPDATE ai_context SET issues_fixed = issues_fixed + 1,
           issues_remaining = GREATEST(0, issues_remaining - 1), updated_at = NOW()
           WHERE channel_id = :cid"""
    ), {"cid": data.channel_id})

    await db.commit()

    return {
        "success": True,
        "fix_id": fix_id,
        "message": f"✅ {data.fix_type} fixed for {data.filename}",
    }


# ── Skip Issue ────────────────────────────────────────────────

@router.post("/skip-issue")
async def skip_issue(data: SkipIssueRequest, db: AsyncSession = Depends(get_db)):
    """Skip an issue (user chose not to fix)."""
    await db.execute(text(
        """UPDATE ai_issues SET status = 'skipped', skipped_at = NOW(), skip_reason = :reason, updated_at = NOW()
           WHERE id = :id"""
    ), {"id": data.issue_id, "reason": data.reason})

    await db.execute(text(
        """UPDATE ai_context SET issues_remaining = GREATEST(0, issues_remaining - 1), updated_at = NOW()
           WHERE channel_id = (SELECT channel_id FROM ai_issues WHERE id = :id)"""
    ), {"id": data.issue_id})

    await db.commit()
    return {"success": True, "message": "Issue skipped"}


# ── Undo Fix ──────────────────────────────────────────────────

@router.post("/undo-fix")
async def undo_fix(data: UndoFixRequest, db: AsyncSession = Depends(get_db)):
    """Revert a fix — reopen the issue."""
    # Get fix details
    result = await db.execute(text(
        "SELECT * FROM ai_fixes WHERE id = :id"
    ), {"id": data.fix_id})
    fix = result.mappings().first()
    if not fix:
        raise HTTPException(status_code=404, detail="Fix not found")

    # Mark fix as reverted
    await db.execute(text(
        "UPDATE ai_fixes SET status = 'reverted', reverted_at = NOW() WHERE id = :id"
    ), {"id": data.fix_id})

    # Reopen issue
    await db.execute(text(
        """UPDATE ai_issues SET status = 'open', fixed_at = NULL, fix_id = NULL, updated_at = NOW()
           WHERE fix_id = :id"""
    ), {"id": data.fix_id})

    # Update context
    await db.execute(text(
        """UPDATE ai_context SET issues_fixed = GREATEST(0, issues_fixed - 1),
           issues_remaining = issues_remaining + 1, updated_at = NOW()
           WHERE channel_id = :cid"""
    ), {"cid": fix["channel_id"]})

    await db.commit()
    return {"success": True, "message": f"Fix #{data.fix_id} reverted"}


# ── History ───────────────────────────────────────────────────

@router.get("/fixes/{channel_id}")
async def get_fixes(channel_id: int, db: AsyncSession = Depends(get_db)):
    """Get applied fixes history for a channel."""
    result = await db.execute(text(
        """SELECT id, filename, fix_type, old_value, new_value, status, applied_at, reverted_at
           FROM ai_fixes WHERE channel_id = :cid ORDER BY applied_at DESC LIMIT 50"""
    ), {"cid": channel_id})
    fixes = [dict(r) for r in result.mappings().all()]
    return {"channel_id": channel_id, "fixes": fixes}


@router.get("/issues/{channel_id}")
async def get_issues(channel_id: int, db: AsyncSession = Depends(get_db)):
    """Get all issues for a channel (open + fixed + skipped)."""
    result = await db.execute(text(
        """SELECT id, filename, issue_type, severity, description, status, fixed_at, skipped_at, detected_at
           FROM ai_issues WHERE channel_id = :cid ORDER BY
           CASE status WHEN 'open' THEN 0 WHEN 'fixed' THEN 1 WHEN 'skipped' THEN 2 ELSE 3 END,
           severity DESC"""
    ), {"cid": channel_id})
    issues = [dict(r) for r in result.mappings().all()]
    return {"channel_id": channel_id, "issues": issues}


@router.get("/context/{channel_id}")
async def get_context(channel_id: int, db: AsyncSession = Depends(get_db)):
    """Get AI context for a channel."""
    result = await db.execute(text(
        "SELECT * FROM ai_context WHERE channel_id = :cid"
    ), {"cid": channel_id})
    ctx = result.mappings().first()
    return {"channel_id": channel_id, "context": dict(ctx) if ctx else None}


# ══════════════════════════════════════════════════════════════
# CONTENT INTELLIGENCE — Pattern Recognition from High-CTR Videos
# ══════════════════════════════════════════════════════════════

import re
from collections import Counter

@router.get("/intelligence/{channel_id}")
async def content_intelligence(channel_id: int, db: AsyncSession = Depends(get_db)):
    """
    Analyze video_analytics to find patterns.
    Compare high-CTR videos vs low-CTR videos.
    Returns actionable content intelligence.
    """
    from app.models.channel import Channel
    from app.models.video_analytics import VideoAnalytics
    from sqlalchemy import func

    # 1. Verify channel
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    # 2. Get latest snapshot
    latest = await db.execute(
        select(func.max(VideoAnalytics.snapshot_date))
        .where(VideoAnalytics.channel_id == channel_id)
    )
    snapshot_date = latest.scalar()
    if not snapshot_date:
        return {"success": False, "error": "No data yet. Run Snapshot first."}

    # 3. Get all videos for latest snapshot
    result = await db.execute(
        select(VideoAnalytics)
        .where(VideoAnalytics.channel_id == channel_id, VideoAnalytics.snapshot_date == snapshot_date)
        .order_by(VideoAnalytics.ctr.desc())
    )
    all_videos = result.scalars().all()

    if not all_videos:
        return {"success": False, "error": "No videos found"}

    # 4. Split into high-CTR (top 25%) and low-CTR (bottom 25%)
    videos_sorted = sorted(all_videos, key=lambda v: v.ctr, reverse=True)
    n = len(videos_sorted)
    high_cutoff = max(1, n // 4)
    low_cutoff = max(1, n // 4)

    high_ctr = [v for v in videos_sorted[:high_cutoff] if v.ctr > 0]
    low_ctr = [v for v in videos_sorted[-low_cutoff:] if v.ctr > 0]

    # 5. Analyze patterns
    def extract_patterns(videos):
        titles = [v.video_title or "" for v in videos]
        words = []
        title_lengths = []
        has_number = 0
        has_hours = 0
        has_question = 0

        for t in titles:
            title_lengths.append(len(t))
            words.extend(re.findall(r'\b\w+\b', t.lower()))
            if re.search(r'\d+', t):
                has_number += 1
            if re.search(r'\d+\s*(hour|hr|jam)', t.lower()):
                has_hours += 1
            if '?' in t:
                has_question += 1

        # Remove common stop words
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
                      'of', 'with', 'by', 'is', 'it', 'as', 'be', 'this', 'that', 'from',
                      'dan', 'di', 'ke', 'yang', 'untuk', 'dengan', 'ini', 'itu', 'pada'}
        filtered_words = [w for w in words if w not in stop_words and len(w) > 2]

        return {
            "top_keywords": Counter(filtered_words).most_common(10),
            "avg_title_length": round(sum(title_lengths) / max(len(title_lengths), 1)),
            "pct_with_number": round(has_number / max(len(titles), 1) * 100),
            "pct_with_hours": round(has_hours / max(len(titles), 1) * 100),
            "pct_with_question": round(has_question / max(len(titles), 1) * 100),
            "sample_titles": titles[:5],
        }

    high_patterns = extract_patterns(high_ctr)
    low_patterns = extract_patterns(low_ctr)

    # 6. Compute stats
    high_avg_ctr = round(sum(v.ctr for v in high_ctr) / max(len(high_ctr), 1), 2)
    low_avg_ctr = round(sum(v.ctr for v in low_ctr) / max(len(low_ctr), 1), 2)
    high_avg_views = round(sum(v.views for v in high_ctr) / max(len(high_ctr), 1))
    low_avg_views = round(sum(v.views for v in low_ctr) / max(len(low_ctr), 1))
    overall_avg_ctr = round(sum(v.ctr for v in all_videos if v.ctr > 0) / max(len([v for v in all_videos if v.ctr > 0]), 1), 2)

    # 7. Build recommendations
    recommendations = []
    if high_patterns["pct_with_hours"] > low_patterns["pct_with_hours"]:
        recommendations.append("Gunakan format '[Durasi] Jam [Sound]' di title — video high-CTR lebih banyak pakai ini")
    if high_patterns["avg_title_length"] > low_patterns["avg_title_length"]:
        recommendations.append(f"Title lebih panjang ({high_patterns['avg_title_length']} char) performa lebih baik dari pendek ({low_patterns['avg_title_length']} char)")
    if high_patterns["top_keywords"]:
        top_kw = [k[0] for k in high_patterns["top_keywords"][:5]]
        recommendations.append(f"Keyword yang sering muncul di video bagus: {', '.join(top_kw)}")
    if low_avg_ctr < 2.0:
        recommendations.append(f"CTR rata-rata video bawah hanya {low_avg_ctr}% — perlu thumbnail & title overhaul")

    return {
        "success": True,
        "channel": channel.name,
        "snapshot_date": str(snapshot_date),
        "total_videos": n,
        "overall_avg_ctr": overall_avg_ctr,
        "high_ctr": {
            "count": len(high_ctr),
            "avg_ctr": high_avg_ctr,
            "avg_views": high_avg_views,
            "patterns": high_patterns,
        },
        "low_ctr": {
            "count": len(low_ctr),
            "avg_ctr": low_avg_ctr,
            "avg_views": low_avg_views,
            "patterns": low_patterns,
        },
        "recommendations": recommendations,
    }


# ══════════════════════════════════════════════════════════════
# SMART TITLE GENERATOR — Based on High-CTR Patterns
# ══════════════════════════════════════════════════════════════

class SuggestTitlesRequest(BaseModel):
    channel_id: int
    topic: str
    count: int = 5

@router.post("/suggest-titles")
async def suggest_titles(data: SuggestTitlesRequest, db: AsyncSession = Depends(get_db)):
    """
    Generate title suggestions based on high-CTR patterns from this channel.
    Uses AI provider configured in ai_settings.
    """
    from app.models.channel import Channel
    from app.models.video_analytics import VideoAnalytics
    from sqlalchemy import func

    # 1. Verify channel
    result = await db.execute(select(Channel).where(Channel.id == data.channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    # 2. Get high-CTR titles for patterns
    latest = await db.execute(
        select(func.max(VideoAnalytics.snapshot_date))
        .where(VideoAnalytics.channel_id == data.channel_id)
    )
    snapshot_date = latest.scalar()

    high_ctr_titles = []
    if snapshot_date:
        result = await db.execute(
            select(VideoAnalytics)
            .where(VideoAnalytics.channel_id == data.channel_id, VideoAnalytics.snapshot_date == snapshot_date)
            .order_by(VideoAnalytics.ctr.desc())
            .limit(10)
        )
        top_videos = result.scalars().all()
        high_ctr_titles = [v.video_title for v in top_videos if v.video_title and v.ctr > 2.0]

    # 3. Load AI settings
    settings_result = await db.execute(text("SELECT * FROM ai_settings ORDER BY id LIMIT 1"))
    settings = settings_result.mappings().first()

    if not settings or not settings.get("api_key") or not settings.get("base_url"):
        # Fallback: return pattern-based suggestions without AI
        templates = [
            f"{data.topic} — Relaxing Sounds for Sleep & Meditation",
            f"Hours {data.topic} for Deep Sleep | Calming Nature Sounds",
            f"{data.topic} — Stress Relief & Focus Music",
            f"Beautiful {data.topic} | 10 Hours Ambient Sound",
            f"{data.topic} — Peaceful Background for Study & Work",
        ]
        return {
            "success": True,
            "method": "template",
            "note": "AI not configured. Using template-based suggestions.",
            "patterns_used": high_ctr_titles[:3],
            "suggestions": [{"title": t, "score": "N/A"} for t in templates[:data.count]],
        }

    # 4. Build AI prompt
    patterns_text = "\n".join([f"- \"{t}\" (CTR: {v.ctr}%)" for t, v in zip(high_ctr_titles, top_videos[:5])]) if high_ctr_titles else "No high-CTR data yet"

    prompt = f"""You are a YouTube title optimizer for a channel in the underwater/relaxation/sleep niche.

Channel: {channel.name}
Topic: {data.topic}

PROVEN HIGH-CTR TITLES from this channel:
{patterns_text}

Generate {data.count} YouTube titles that:
1. Follow patterns from high-CTR titles above
2. Include duration (hours) if relevant
3. Include purpose keywords (sleep, relaxation, meditation, focus)
4. Are SEO-friendly and click-worthy
5. Under 60 characters if possible

Return ONLY a JSON array: [{{"title": "...", "reason": "why this works"}}]"""

    # 5. Call AI
    try:
        provider = settings.get("provider", "9router")
        base_url = settings.get("base_url", "")
        api_key = settings.get("api_key", "")
        model = settings.get("model", "wf/mimo-mimo-v2.5-pro")

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 500,
                    "temperature": 0.8,
                },
            )

        if resp.status_code != 200:
            raise Exception(f"AI returned {resp.status_code}: {resp.text[:200]}")

        ai_response = resp.json()
        content = ai_response.get("choices", [{}])[0].get("message", {}).get("content", "")

        # Parse JSON from response
        # Try to extract JSON array from response
        json_match = re.search(r'\[.*\]', content, re.DOTALL)
        if json_match:
            suggestions = json.loads(json_match.group())
        else:
            suggestions = [{"title": content.strip(), "reason": "AI generated"}]

        return {
            "success": True,
            "method": "ai",
            "model": model,
            "patterns_used": high_ctr_titles[:3],
            "suggestions": suggestions[:data.count],
        }

    except Exception as e:
        log.error(f"AI title generation failed: {e}")
        return {
            "success": False,
            "error": str(e)[:200],
            "fallback": True,
            "suggestions": [{"title": f"{data.topic} — Relaxing Sounds", "reason": "fallback"}],
        }
