from sqlalchemy import Column, Integer, String, DateTime, Text, JSON
from sqlalchemy.sql import func
from app.models.base import Base


class AssetUsageLog(Base):
    __tablename__ = "asset_usage_logs"

    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, nullable=False, index=True)
    asset_key = Column(String(1000), nullable=True)  # relative path e.g. assets/video/1/file.mp4
    asset_source = Column(String(500), nullable=True)
    asset_filename = Column(String(500), nullable=True)
    file_path = Column(String(1000), nullable=False)
    asset_type = Column(String(50), nullable=False)  # video, mp3, sfx
    usage_type = Column(String(50), nullable=False)  # upload_regular, livestream, production
    used_for = Column(String(50), nullable=True)  # legacy alias
    usage_date = Column(DateTime(timezone=True), server_default=func.now())
    cooldown_until = Column(DateTime(timezone=True), nullable=True)
    related_type = Column(String(100), nullable=True)
    related_id = Column(Integer, nullable=True)
    meta_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
