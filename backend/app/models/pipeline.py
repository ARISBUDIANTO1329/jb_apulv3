from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, JSON
from sqlalchemy.sql import func
from app.models.base import Base


class Pipeline(Base):
    __tablename__ = "pipelines"

    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, nullable=False, index=True)

    # Mode
    mode = Column(String(50), default="final")  # dynamic, static, final, direct

    # Upload config
    upload_enabled = Column(Boolean, default=True)
    upload_count = Column(Integer, default=3)

    # Livestream config
    live_enabled = Column(Boolean, default=False)
    live_count = Column(Integer, default=1)
    live_duration_hours = Column(Integer, default=12)
    live_quality = Column(String(50), default="low")
    live_use_mp3 = Column(Boolean, default=True)
    live_use_sfx = Column(Boolean, default=True)

    # Shorts config
    shorts_enabled = Column(Boolean, default=False)
    shorts_count = Column(Integer, default=3)

    # Schedule
    scheduler_time = Column(String(10), nullable=True)  # HH:MM in WIB

    # Status
    is_active = Column(Boolean, default=True)

    # Full config as JSON
    config_json = Column(JSON, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id = Column(Integer, primary_key=True, index=True)
    pipeline_id = Column(Integer, nullable=False, index=True)
    channel_id = Column(Integer, nullable=False, index=True)

    # Status
    status = Column(String(50), default="pending")  # pending, producing, uploading, livestreaming, completed, failed, partial
    current_stage = Column(String(50), default="pending")
    progress = Column(Integer, default=0)

    # Run type
    run_type = Column(String(50), default="manual")  # manual, scheduled

    # Schedule
    scheduled_at = Column(DateTime(timezone=True), nullable=True)

    # Log
    log = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    result_json = Column(JSON, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    finished_at = Column(DateTime(timezone=True), nullable=True)
