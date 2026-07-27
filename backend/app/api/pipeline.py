from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional, Any

from app.db.session import get_db
from app.models.pipeline import Pipeline, PipelineRun
from app.models.channel import Channel

router = APIRouter()


class PipelineCreate(BaseModel):
    channel_id: int
    mode: str = "final"
    upload_enabled: bool = True
    upload_count: int = 3
    live_enabled: bool = False
    live_count: int = 1
    live_duration_hours: int = 12
    live_quality: str = "low"
    scheduler_time: Optional[str] = None  # HH:MM in WIB


class PipelineUpdate(BaseModel):
    mode: Optional[str] = None
    upload_enabled: Optional[bool] = None
    upload_count: Optional[int] = None
    live_enabled: Optional[bool] = None
    live_count: Optional[int] = None
    live_duration_hours: Optional[int] = None
    live_quality: Optional[str] = None
    scheduler_time: Optional[str] = None
    is_active: Optional[bool] = None
    config_json: Optional[dict] = None


class SaveUploadConfig(BaseModel):
    mode: Optional[str] = None
    upload_count: Optional[int] = None
    upload_enabled: Optional[bool] = None
    scheduler_time: Optional[str] = None
    # Audio settings
    use_mp3: Optional[bool] = None
    use_sfx: Optional[bool] = None
    num_songs: Optional[int] = None
    duration_mode: Optional[str] = None
    custom_duration: Optional[str] = None
    mp3_mode: Optional[str] = None
    mp3_file: Optional[str] = None
    sfx_file: Optional[str] = None
    intro_file: Optional[str] = None
    # Dynamic settings
    merge_count: Optional[int] = None
    dynamic_output_count: Optional[int] = None
    merge_resolution: Optional[str] = None
    merge_transition_enabled: Optional[bool] = None
    merge_transition_name: Optional[str] = None
    merge_transition_duration: Optional[float] = None
    # Static settings
    tail_length: Optional[int] = None
    slowmo_percent: Optional[int] = None


class SaveLivestreamConfig(BaseModel):
    live_mode: Optional[str] = None
    live_enabled: Optional[bool] = None
    live_count: Optional[int] = None
    live_duration_hours: Optional[int] = None
    live_quality: Optional[str] = None
    live_use_mp3: Optional[bool] = None
    live_use_sfx: Optional[bool] = None


class SaveShortsConfig(BaseModel):
    shorts_enabled: Optional[bool] = None
    shorts_count: Optional[int] = None
    shorts_mode: Optional[str] = None
    shorts_duration_min: Optional[int] = None
    shorts_duration_max: Optional[int] = None
    shorts_merge_count: Optional[int] = None
    shorts_text_overlay: Optional[bool] = None
    shorts_music_overlay: Optional[bool] = None
    shorts_transition: Optional[str] = None
    shorts_transition_duration: Optional[float] = None
    shorts_slowmo_enabled: Optional[bool] = None
    shorts_slowmo_factor: Optional[float] = None
    shorts_loop_if_short: Optional[bool] = None
    shorts_cut_if_long: Optional[bool] = None
    shorts_schedule_time: Optional[str] = None
    shorts_interval_minutes: Optional[int] = None


@router.get("")
async def list_pipelines(db: AsyncSession = Depends(get_db)):
    """List all pipelines."""
    result = await db.execute(select(Pipeline).order_by(Pipeline.channel_id))
    pipelines = result.scalars().all()

    return [{
        "id": p.id,
        "channel_id": p.channel_id,
        "mode": p.mode,
        "upload_enabled": p.upload_enabled,
        "upload_count": p.upload_count,
        "live_enabled": p.live_enabled,
        "live_count": p.live_count,
        "live_duration_hours": p.live_duration_hours,
        "live_quality": p.live_quality,
        "shorts_enabled": p.shorts_enabled,
        "shorts_count": p.shorts_count,
        "scheduler_time": p.scheduler_time,
        "is_active": p.is_active,
        "config_json": p.config_json,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    } for p in pipelines]


@router.get("/{pipeline_id}")
async def get_pipeline(pipeline_id: int, db: AsyncSession = Depends(get_db)):
    """Get pipeline details."""
    result = await db.execute(select(Pipeline).where(Pipeline.id == pipeline_id))
    pipeline = result.scalar_one_or_none()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    return {
        "id": pipeline.id,
        "channel_id": pipeline.channel_id,
        "mode": pipeline.mode,
        "upload_enabled": pipeline.upload_enabled,
        "upload_count": pipeline.upload_count,
        "live_enabled": pipeline.live_enabled,
        "live_count": pipeline.live_count,
        "live_duration_hours": pipeline.live_duration_hours,
        "live_quality": pipeline.live_quality,
        "live_use_mp3": pipeline.live_use_mp3,
        "live_use_sfx": pipeline.live_use_sfx,
        "shorts_enabled": pipeline.shorts_enabled,
        "shorts_count": pipeline.shorts_count,
        "scheduler_time": pipeline.scheduler_time,
        "is_active": pipeline.is_active,
        "config_json": pipeline.config_json,
        "created_at": pipeline.created_at.isoformat() if pipeline.created_at else None,
    }


@router.post("")
async def create_pipeline(data: PipelineCreate, db: AsyncSession = Depends(get_db)):
    """Create a pipeline for a channel."""
    result = await db.execute(select(Channel).where(Channel.id == data.channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    existing = await db.execute(select(Pipeline).where(Pipeline.channel_id == data.channel_id))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Pipeline already exists for this channel")

    pipeline = Pipeline(
        channel_id=data.channel_id,
        mode=data.mode,
        upload_enabled=data.upload_enabled,
        upload_count=data.upload_count,
        live_enabled=data.live_enabled,
        live_count=data.live_count,
        live_duration_hours=data.live_duration_hours,
        live_quality=data.live_quality,
        scheduler_time=data.scheduler_time,
    )
    db.add(pipeline)
    await db.flush()
    await db.refresh(pipeline)

    return {"success": True, "id": pipeline.id}


@router.put("/{pipeline_id}")
async def update_pipeline(pipeline_id: int, data: PipelineUpdate, db: AsyncSession = Depends(get_db)):
    """Update a pipeline."""
    result = await db.execute(select(Pipeline).where(Pipeline.id == pipeline_id))
    pipeline = result.scalar_one_or_none()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(pipeline, key, value)

    return {"success": True}


# ── Toggle ───────────────────────────────────────────────────────


@router.post("/{pipeline_id}/toggle")
async def toggle_pipeline(pipeline_id: int, db: AsyncSession = Depends(get_db)):
    """Toggle pipeline on/off."""
    result = await db.execute(select(Pipeline).where(Pipeline.id == pipeline_id))
    pipeline = result.scalar_one_or_none()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    pipeline.is_active = not pipeline.is_active
    return {"success": True, "is_active": pipeline.is_active}


@router.post("/{pipeline_id}/toggle-feature")
async def toggle_feature(pipeline_id: int, feature: str = Query(...), db: AsyncSession = Depends(get_db)):
    """Toggle a specific feature (upload, live, shorts)."""
    result = await db.execute(select(Pipeline).where(Pipeline.id == pipeline_id))
    pipeline = result.scalar_one_or_none()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    if feature == "upload":
        pipeline.upload_enabled = not pipeline.upload_enabled
        return {"success": True, "feature": "upload", "enabled": pipeline.upload_enabled}
    elif feature == "live":
        pipeline.live_enabled = not pipeline.live_enabled
        return {"success": True, "feature": "live", "enabled": pipeline.live_enabled}
    elif feature == "shorts":
        pipeline.shorts_enabled = not pipeline.shorts_enabled
        return {"success": True, "feature": "shorts", "enabled": pipeline.shorts_enabled}
    else:
        raise HTTPException(status_code=400, detail="Invalid feature")


# ── Save Config ──────────────────────────────────────────────────


@router.post("/{pipeline_id}/save-upload")
async def save_upload_config(pipeline_id: int, data: SaveUploadConfig, db: AsyncSession = Depends(get_db)):
    """Save upload configuration for a pipeline."""
    result = await db.execute(select(Pipeline).where(Pipeline.id == pipeline_id))
    pipeline = result.scalar_one_or_none()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    # Update pipeline fields
    update_data = data.model_dump(exclude_unset=True)
    config = pipeline.config_json or {}
    upload_config = config.get("upload_production", {})

    # Separate pipeline-level fields from config-level fields
    pipeline_fields = {"mode", "upload_count", "upload_enabled", "scheduler_time"}
    for key, value in update_data.items():
        if key in pipeline_fields:
            setattr(pipeline, key, value)
        else:
            upload_config[key] = value

    config["upload_production"] = upload_config
    pipeline.config_json = config

    return {"success": True}


@router.post("/{pipeline_id}/save-livestream")
async def save_livestream_config(pipeline_id: int, data: SaveLivestreamConfig, db: AsyncSession = Depends(get_db)):
    """Save livestream configuration for a pipeline."""
    result = await db.execute(select(Pipeline).where(Pipeline.id == pipeline_id))
    pipeline = result.scalar_one_or_none()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    update_data = data.model_dump(exclude_unset=True)
    config = pipeline.config_json or {}
    live_config = config.get("livestream_production", {})

    pipeline_fields = {"live_mode", "live_enabled", "live_count", "live_duration_hours", "live_quality", "live_use_mp3", "live_use_sfx"}
    for key, value in update_data.items():
        if key in pipeline_fields:
            setattr(pipeline, key, value)
        else:
            live_config[key] = value

    config["livestream_production"] = live_config
    pipeline.config_json = config

    return {"success": True}


@router.post("/{pipeline_id}/save-shorts")
async def save_shorts_config(pipeline_id: int, data: SaveShortsConfig, db: AsyncSession = Depends(get_db)):
    """Save shorts configuration for a pipeline."""
    result = await db.execute(select(Pipeline).where(Pipeline.id == pipeline_id))
    pipeline = result.scalar_one_or_none()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    update_data = data.model_dump(exclude_unset=True)
    config = pipeline.config_json or {}
    shorts_config = config.get("shorts_production", {})

    pipeline_fields = {"shorts_enabled", "shorts_count"}
    for key, value in update_data.items():
        if key in pipeline_fields:
            setattr(pipeline, key, value)
        else:
            shorts_config[key] = value

    config["shorts_production"] = shorts_config
    pipeline.config_json = config

    return {"success": True}


@router.post("/{pipeline_id}/save-config")
async def save_general_config(pipeline_id: int, data: dict, db: AsyncSession = Depends(get_db)):
    """Save general config JSON for a pipeline."""
    result = await db.execute(select(Pipeline).where(Pipeline.id == pipeline_id))
    pipeline = result.scalar_one_or_none()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    config = pipeline.config_json or {}
    config.update(data)
    pipeline.config_json = config

    return {"success": True}


# ── Run Actions ──────────────────────────────────────────────────


@router.post("/{pipeline_id}/run")
async def run_pipeline(pipeline_id: int, db: AsyncSession = Depends(get_db)):
    """Trigger a manual pipeline run."""
    result = await db.execute(select(Pipeline).where(Pipeline.id == pipeline_id))
    pipeline = result.scalar_one_or_none()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    # Check if there's already an active run
    active = await db.execute(
        select(PipelineRun)
        .where(PipelineRun.pipeline_id == pipeline_id)
        .where(PipelineRun.status.in_(["pending", "producing", "uploading", "livestreaming"]))
    )
    if active.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Pipeline already has an active run")

    run = PipelineRun(
        pipeline_id=pipeline.id,
        channel_id=pipeline.channel_id,
        status="pending",
        run_type="manual",
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)

    return {
        "success": True,
        "run_id": run.id,
        "status": "pending",
        "message": "Pipeline run created. Worker will pick it up.",
    }


@router.post("/{pipeline_id}/start")
async def start_pipeline(pipeline_id: int, db: AsyncSession = Depends(get_db)):
    """Start/resume a pipeline (set active)."""
    result = await db.execute(select(Pipeline).where(Pipeline.id == pipeline_id))
    pipeline = result.scalar_one_or_none()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    pipeline.is_active = True
    return {"success": True, "is_active": True}


@router.post("/{pipeline_id}/pause")
async def pause_pipeline(pipeline_id: int, db: AsyncSession = Depends(get_db)):
    """Pause a pipeline."""
    result = await db.execute(select(Pipeline).where(Pipeline.id == pipeline_id))
    pipeline = result.scalar_one_or_none()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    pipeline.is_active = False
    return {"success": True, "is_active": False}


@router.post("/{pipeline_id}/resume")
async def resume_pipeline(pipeline_id: int, db: AsyncSession = Depends(get_db)):
    """Resume a paused pipeline."""
    result = await db.execute(select(Pipeline).where(Pipeline.id == pipeline_id))
    pipeline = result.scalar_one_or_none()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    pipeline.is_active = True
    return {"success": True, "is_active": True}


# ── Active Run ───────────────────────────────────────────────────


@router.get("/{pipeline_id}/active-run")
async def get_active_run(pipeline_id: int, db: AsyncSession = Depends(get_db)):
    """Get the currently active run for a pipeline."""
    result = await db.execute(
        select(PipelineRun)
        .where(PipelineRun.pipeline_id == pipeline_id)
        .where(PipelineRun.status.in_(["pending", "producing", "uploading", "livestreaming"]))
        .order_by(PipelineRun.created_at.desc())
        .limit(1)
    )
    run = result.scalar_one_or_none()
    if not run:
        return {"active": False}

    return {
        "active": True,
        "run_id": run.id,
        "status": run.status,
        "current_stage": run.current_stage,
        "progress": run.progress,
        "run_type": run.run_type,
        "error_message": run.error_message,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


@router.get("/run/{run_id}/status")
async def get_run_status(run_id: int, db: AsyncSession = Depends(get_db)):
    """Get status of a specific pipeline run."""
    result = await db.execute(select(PipelineRun).where(PipelineRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    return {
        "id": run.id,
        "pipeline_id": run.pipeline_id,
        "channel_id": run.channel_id,
        "status": run.status,
        "current_stage": run.current_stage,
        "progress": run.progress,
        "run_type": run.run_type,
        "error_message": run.error_message,
        "log": run.log,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


@router.post("/run/{run_id}/cancel")
async def cancel_run(run_id: int, db: AsyncSession = Depends(get_db)):
    """Cancel a running pipeline run."""
    result = await db.execute(select(PipelineRun).where(PipelineRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    if run.status in ["completed", "failed", "cancelled"]:
        raise HTTPException(status_code=400, detail=f"Cannot cancel run in '{run.status}' state")

    run.status = "cancelled"
    return {"success": True, "status": "cancelled"}


# ── Runs History ─────────────────────────────────────────────────


@router.get("/{pipeline_id}/runs")
async def list_runs(pipeline_id: int, limit: int = Query(20), db: AsyncSession = Depends(get_db)):
    """List pipeline runs."""
    result = await db.execute(
        select(PipelineRun)
        .where(PipelineRun.pipeline_id == pipeline_id)
        .order_by(PipelineRun.created_at.desc())
        .limit(limit)
    )
    runs = result.scalars().all()

    return [{
        "id": r.id,
        "pipeline_id": r.pipeline_id,
        "channel_id": r.channel_id,
        "status": r.status,
        "current_stage": r.current_stage,
        "progress": r.progress,
        "run_type": r.run_type,
        "error_message": r.error_message,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
    } for r in runs]


@router.delete("/{pipeline_id}")
async def delete_pipeline(pipeline_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a pipeline."""
    result = await db.execute(select(Pipeline).where(Pipeline.id == pipeline_id))
    pipeline = result.scalar_one_or_none()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    # Delete all runs first
    await db.execute(
        select(PipelineRun).where(PipelineRun.pipeline_id == pipeline_id)
    )

    await db.delete(pipeline)
    return {"success": True}
