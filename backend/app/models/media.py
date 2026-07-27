from sqlalchemy import Column, Integer, String, Text, DateTime, JSON
from sqlalchemy.sql import func
from app.models.base import Base


class MediaItem(Base):
    __tablename__ = "media_items"

    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, nullable=False, index=True)
    filename = Column(String(500), nullable=False)
    original_name = Column(String(500), nullable=True)  # nama asli sebelum rename
    file_path = Column(String(1000), nullable=False)
    asset_type = Column(String(50), nullable=False, index=True)  # video, video-raw, video-live, livestream-ready, mp3, sfx, intro, thumbnail, metadata, upload_ready
    mime = Column(String(100), nullable=True)  # video/mp4, audio/mpeg, dll
    file_size = Column(Integer, nullable=True)  # bytes
    duration = Column(Integer, nullable=True)  # seconds
    title = Column(String(500), nullable=True)  # judul (untuk metadata)
    note = Column(Text, nullable=True)  # catatan
    tags = Column(Text, nullable=True)  # tags comma-separated
    status = Column(String(50), nullable=True, default="ready")  # ready, processing, uploaded
    category = Column(String(100), nullable=True)  # title_bank, description_bank, tag_bank (untuk metadata)
    sha256 = Column(String(64), nullable=True)  # hash file
    metadata_json = Column(JSON, nullable=True)  # JSON extra data
    scheduled_at = Column(DateTime(timezone=True), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    youtube_video_id = Column(String(50), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
