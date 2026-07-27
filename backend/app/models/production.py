from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Float, JSON
from sqlalchemy.sql import func
from app.models.base import Base


class ProductionJob(Base):
    __tablename__ = "production_jobs"

    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, nullable=False, index=True)

    # Source
    video_source = Column(String(500), nullable=True)
    num_songs = Column(Integer, default=1)
    no_mp3 = Column(Boolean, default=False)
    no_sfx = Column(Boolean, default=False)
    sfx_file = Column(String(255), nullable=True)
    intro_file = Column(String(255), nullable=True)
    mp3_file = Column(String(255), nullable=True)
    duration_mode = Column(String(50), default="auto")  # mp3, manual
    custom_duration = Column(Integer, nullable=True)  # seconds

    # Production mode
    production_mode = Column(String(50), default="v2")  # v2, dynamic, static, final
    production_method = Column(String(50), default="ready_video")  # ready_video, raw_video_auto_seamless, merge_video
    mp3_mode = Column(String(50), default="shuffle")  # shuffle, single
    tail_length = Column(Integer, default=3)  # 1-5 seconds for static video
    slowmo_percent = Column(Integer, default=0)  # 0-50 for static video

    # Output
    output_filename = Column(String(500), nullable=True)

    # Dynamic merge config (stored per job for worker)
    merge_count = Column(Integer, default=10)
    merge_resolution = Column(String(20), default="1920x1080")
    merge_transition_enabled = Column(Boolean, default=True)
    merge_transition_name = Column(String(50), default="fade")
    merge_transition_duration = Column(Float, default=1.0)
    merge_speed = Column(Float, default=1.0)
    dynamic_output_count = Column(Integer, default=1)

    # Status tracking (3-stage)
    status = Column(String(50), default="pending")  # pending, processing, done, failed
    progress = Column(Integer, default=0)
    audio_status = Column(String(50), default="pending")
    video_status = Column(String(50), default="pending")
    final_status = Column(String(50), default="pending")

    # Paths
    audio_path = Column(String(1000), nullable=True)
    video_path = Column(String(1000), nullable=True)
    final_path = Column(String(1000), nullable=True)

    # Audio duration
    audio_duration = Column(Integer, nullable=True)  # seconds

    # Error
    error_message = Column(Text, nullable=True)
    process_status = Column(String(255), nullable=True)
    process_log = Column(JSON, nullable=True, default=list)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
