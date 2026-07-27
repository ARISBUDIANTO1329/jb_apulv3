"""Shorts Generator Models - Auto-generate shorts from completed uploads."""

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from app.models.base import Base


class ShortsJob(Base):
    """Parent job for shorts generation from a completed upload."""
    __tablename__ = "shorts_jobs"

    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False)

    # Link to completed upload
    long_upload_id = Column(Integer, nullable=True)  # Reference to upload_batch_items.id
    long_youtube_url = Column(String(500), nullable=True)
    long_title = Column(String(500), nullable=True)

    # Settings
    short_count = Column(Integer, default=3)
    short_duration = Column(Integer, default=60)  # seconds
    segment_mode = Column(String(20), default="auto")  # auto / manual
    description_template = Column(Text, nullable=True)

    # Schedule (WIB times)
    upload_time_1 = Column(String(10), default="12:00")  # HH:MM
    upload_time_2 = Column(String(10), default="16:00")
    upload_time_3 = Column(String(10), default="20:00")

    # Status
    status = Column(String(50), default="created")  # created, generating, ready, uploading, completed, failed
    error_message = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Auto-update timestamp
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ShortsItem(Base):
    """Individual short video to be generated and uploaded."""
    __tablename__ = "shorts_items"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("shorts_jobs.id"), nullable=False)
    short_number = Column(Integer, nullable=False)  # 1, 2, 3

    # Video source (after generation)
    video_path = Column(String(500), nullable=True)
    start_second = Column(Integer, nullable=True)
    end_second = Column(Integer, nullable=True)

    # Upload metadata
    title = Column(String(500), nullable=True)
    description = Column(Text, nullable=True)
    youtube_id = Column(String(100), nullable=True)

    # Schedule
    upload_time = Column(String(10), nullable=True)  # HH:MM

    # Status
    status = Column(String(50), default="pending")  # pending, generated, uploading, uploaded, failed
    error_message = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    uploaded_at = Column(DateTime(timezone=True), nullable=True)
