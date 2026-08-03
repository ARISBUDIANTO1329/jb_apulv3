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


# ── Analyze Channel (Context-Aware) ──────────────────────────

@router.post("/analyze/{channel_id}")
async def analyze_channel(channel_id: int, db: AsyncSession = Depends(get_db)):
    """Analyze channel with context awareness — skip already-fixed items."""
    from app.models.channel import Channel
    from app.models.media import MediaItem

    # Get channel
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    # 1. Load existing fixes (DO NOT repeat)
    fixes_result = await db.execute(text(
        "SELECT filename, fix_type, new_value, applied_at FROM ai_fixes WHERE channel_id = :cid AND status = 'applied' ORDER BY applied_at DESC"
    ), {"cid": channel_id})
    applied_fixes = [dict(r) for r in fixes_result.mappings().all()]

    # 2. Load open issues
    issues_result = await db.execute(text(
        "SELECT * FROM ai_issues WHERE channel_id = :cid AND status = 'open' ORDER BY severity DESC, detected_at DESC"
    ), {"cid": channel_id})
    open_issues = [dict(r) for r in issues_result.mappings().all()]

    # 3. Load context
    ctx_result = await db.execute(text(
        "SELECT * FROM ai_context WHERE channel_id = :cid"
    ), {"cid": channel_id})
    context = dict(ctx_result.mappings().first() or {})

    # 4. Get videos
    media_result = await db.execute(
        select(MediaItem)
        .where(MediaItem.channel_id == channel_id)
        .where(MediaItem.asset_type.in_(["video", "upload_ready"]))
        .order_by(MediaItem.created_at.desc())
    )
    media_items = media_result.scalars().all()

    # 5. Build fixed set (skip these)
    fixed_set = set()
    for fix in applied_fixes:
        fixed_set.add((fix["filename"], fix["fix_type"]))

    # 6. Detect issues for videos NOT yet fixed
    new_issues = []
    for item in media_items:
        filename = item.filename
        name = item.original_name or filename
        stem = name.rsplit(".", 1)[0] if "." in name else name

        # Check title quality (simple heuristic)
        is_bad_title = (
            len(stem) < 10
            or stem.startswith("final_")
            or stem.startswith("UPL")
            or stem.startswith("HEALIN")
            or "_" in stem
            or stem == stem.upper()
        )

        if is_bad_title and (filename, "title") not in fixed_set:
            new_issues.append({
                "filename": filename,
                "issue_type": "bad_title",
                "severity": "high",
                "description": f"Title '{stem}' is not SEO-friendly",
            })

    # 7. Save new issues to DB (upsert — don't duplicate)
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

    # 8. Reload all open issues
    issues_result = await db.execute(text(
        "SELECT * FROM ai_issues WHERE channel_id = :cid AND status = 'open' ORDER BY severity DESC"
    ), {"cid": channel_id})
    all_open = [dict(r) for r in issues_result.mappings().all()]

    # 9. Generate suggestions for open issues
    actions = []
    for issue in all_open:
        stem = issue["filename"].rsplit(".", 1)[0] if "." in issue["filename"] else issue["filename"]
        if stem.startswith("final_"):
            stem = stem[6:]
        if stem.startswith("HEALIN") or stem.startswith("UPL"):
            stem = stem.replace("HEALIN-", "").replace("UPL", "")

        niche = channel.niche or "nature"
        niche_tags = {
            "underwater": ["underwater", "ocean", "marine life", "coral reef", "relaxing", "4k"],
            "nature": ["nature", "scenic", "landscape", "relaxation", "ambient", "4k"],
            "music": ["music", "ambient", "chill", "lofi", "relaxing", "study music"],
        }
        base_tags = niche_tags.get(niche, niche_tags["nature"])

        actions.append({
            "issue_id": issue["id"],
            "type": issue["issue_type"],
            "severity": issue["severity"],
            "filename": issue["filename"],
            "description": issue["description"],
            "suggested_titles": [
                f"{stem} — 4K Relaxing Video for Sleep & Meditation",
                f"Beautiful {stem} 🌊 Calming Nature Ambience",
                f"{stem} | 10 Hours of Pure Relaxation",
            ],
            "suggested_description": f"Experience the beauty of {stem} in stunning 4K quality. Perfect for relaxation, meditation, study, and sleep. Subscribe for more calming content!",
            "suggested_tags": base_tags + [stem.lower(), "relaxing video", "sleep"],
            "thumbnail_prompt": f"Stunning {stem} scene, vibrant colors, cinematic lighting, 4K ultra detailed, photorealistic, calming atmosphere",
        })

    # 10. Update context
    await db.execute(text(
        """INSERT INTO ai_context (channel_id, last_analyze_at, total_issues_found, issues_fixed, issues_remaining, updated_at)
           VALUES (:cid, NOW(), :total, :fixed, :remaining, NOW())
           ON CONFLICT (channel_id) DO UPDATE SET
               last_analyze_at = NOW(),
               total_issues_found = :total,
               issues_fixed = :fixed,
               issues_remaining = :remaining,
               updated_at = NOW()"""
    ), {
        "cid": channel_id,
        "total": len(applied_fixes) + len(all_open),
        "fixed": len(applied_fixes),
        "remaining": len(all_open),
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
