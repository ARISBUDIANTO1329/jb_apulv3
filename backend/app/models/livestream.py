from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Float
from sqlalchemy.sql import func
from app.models.base import Base


class LiveJob(Base):
    __tablename__ = "live_jobs"

    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, nullable=False, index=True)

    # Content
    title = Column(String(500), nullable=True)
    description = Column(Text, nullable=True)
    tags = Column(Text, nullable=True)

    # Video source
    video_source = Column(String(1000), nullable=True)  # folder|filename format
    use_mp3 = Column(Boolean, default=True)
    use_sfx = Column(Boolean, default=True)

    # Stream
    stream_key = Column(String(255), nullable=True)
    broadcast_id = Column(String(100), nullable=True)
    quality = Column(String(50), default="low")  # high (1080p), low (720p)
    visibility = Column(String(50), default="unlisted")

    # Schedule
    duration_hours = Column(Integer, default=12)
    start_at_utc = Column(DateTime(timezone=True), nullable=True)
    end_at_utc = Column(DateTime(timezone=True), nullable=True)

    # Status
    status = Column(String(50), default="pending")  # pending, scheduled, ready, running, finished, failed, stopped
    process_id = Column(Integer, nullable=True)  # ffmpeg PID
    error_message = Column(Text, nullable=True)

    # Health
    reconnect_count = Column(Integer, default=0)
    reconnect_attempts = Column(Integer, default=0)
    last_health_check = Column(DateTime(timezone=True), nullable=True)
    made_for_kids = Column(Boolean, default=False)
    thumbnail_path = Column(String(500), nullable=True)

    # Real-time monitoring
    stream_stats = Column(Text, nullable=True)  # JSON: bitrate, fps, drops, speed
    current_bitrate = Column(Integer, nullable=True)  # kbps
    current_fps = Column(Float, nullable=True)
    viewer_count = Column(Integer, default=0)
    frame_drop_count = Column(Integer, default=0)

    # Error handling
    error_category = Column(String(50), nullable=True)  # network, auth, quota, ffmpeg, unknown
    retry_count = Column(Integer, default=0)
    last_retry_at = Column(DateTime(timezone=True), nullable=True)
    max_retries = Column(Integer, default=3)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
