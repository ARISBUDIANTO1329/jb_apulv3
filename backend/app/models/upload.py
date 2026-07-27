from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func
from app.models.base import Base


class UploadBatch(Base):
    __tablename__ = "upload_batches"

    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, nullable=False, index=True)
    name = Column(String(255), nullable=True)
    status = Column(String(50), default="pending")  # pending, processing, done, partial
    total_items = Column(Integer, default=0)
    done_items = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class UploadBatchItem(Base):
    __tablename__ = "upload_batch_items"

    id = Column(Integer, primary_key=True, index=True)
    upload_batch_id = Column(Integer, ForeignKey("upload_batches.id"), nullable=False)
    channel_id = Column(Integer, nullable=False, index=True)
    media_item_id = Column(Integer, ForeignKey("media_items.id"), nullable=True)

    # Content
    title = Column(String(500), nullable=True)
    description = Column(Text, nullable=True)
    tags = Column(Text, nullable=True)

    # YouTube
    youtube_video_id = Column(String(50), nullable=True)
    scheduled_at = Column(DateTime(timezone=True), nullable=True)
    visibility = Column(String(50), default="private")  # private, unlisted, public, scheduled

    # Status
    status = Column(String(50), default="pending")  # pending, processing, done, failed
    last_error = Column(Text, nullable=True)
    progress = Column(Integer, default=0)

    # Source file
    source_path = Column(String(1000), nullable=True)

    # Thumbnail
    thumbnail_path = Column(String(1000), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    finished_at = Column(DateTime(timezone=True), nullable=True)
