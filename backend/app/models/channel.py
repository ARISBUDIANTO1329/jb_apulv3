from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, JSON
from sqlalchemy.sql import func
from app.models.base import Base


class Channel(Base):
    __tablename__ = "channels"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    youtube_channel_id = Column(String(255), unique=True, nullable=True)
    youtube_channel_url = Column(String(500), nullable=True)
    niche = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    email = Column(String(255), nullable=True)
    status = Column(String(50), default="active")  # active, paused, dropped

    # YouTube OAuth
    access_token = Column(Text, nullable=True)
    refresh_token = Column(Text, nullable=True)
    token_expires_at = Column(DateTime(timezone=True), nullable=True)
    token_status = Column(String(20), default="valid")
    token_error = Column(Text, nullable=True)
    token_checked_at = Column(DateTime(timezone=True), nullable=True)

    # Stream key for livestream
    stream_key = Column(String(255), nullable=True)

    # Proxy (per-channel)
    proxy_host = Column(String(255), nullable=True)
    proxy_port = Column(Integer, nullable=True)
    proxy_type = Column(String(20), nullable=True)  # socks5, socks4, http

    # Chrome profile (for manual operations)
    chrome_profile = Column(String(255), nullable=True)

    # Stats (cached from YouTube API)
    subscriber_count = Column(Integer, default=0)
    total_views = Column(Integer, default=0)
    video_count = Column(Integer, default=0)

    # Notes
    notes = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_upload = Column(DateTime(timezone=True), nullable=True)
    last_livestream = Column(DateTime(timezone=True), nullable=True)
