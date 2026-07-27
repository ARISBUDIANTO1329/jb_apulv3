from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from app.models.base import Base


class EstafetJob(Base):
    __tablename__ = "estafet_jobs"

    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False)
    title = Column(String(500), nullable=False)
    duration_hours = Column(Integer, default=12)
    break_minutes = Column(Integer, default=60)
    quality = Column(String(50), default="low")
    use_mp3 = Column(Boolean, default=True)
    use_sfx = Column(Boolean, default=True)
    status = Column(String(50), default="pending")
    current_video_index = Column(Integer, default=0)
    started_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class EstafetItem(Base):
    __tablename__ = "estafet_videos"

    id = Column(Integer, primary_key=True, index=True)
    estafet_job_id = Column(Integer, ForeignKey("estafet_jobs.id", ondelete="CASCADE"), nullable=False)
    media_item_id = Column(Integer, ForeignKey("media_items.id"), nullable=False)
    video_order = Column(Integer, nullable=False)
    title = Column(String(500), nullable=True)
    description = Column(Text, nullable=True)
    tags = Column(Text, nullable=True)
    thumbnail_path = Column(String(500), nullable=True)
    status = Column(String(50), default="pending")
    youtube_broadcast_id = Column(String(100), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
