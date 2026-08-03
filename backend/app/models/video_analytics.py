from sqlalchemy import Column, Integer, String, Float, Date, DateTime, UniqueConstraint
from sqlalchemy.sql import func
from app.models.base import Base


class VideoAnalytics(Base):
    __tablename__ = "video_analytics"

    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, nullable=False, index=True)
    video_id = Column(String(50), nullable=False, index=True)
    video_title = Column(String(500), nullable=True)
    thumbnail_url = Column(String(1000), nullable=True)

    # Metrics snapshot
    snapshot_date = Column(Date, nullable=False)
    impressions = Column(Integer, default=0)
    ctr = Column(Float, default=0.0)  # impressionClickThroughRate (%)
    views = Column(Integer, default=0)
    watch_minutes = Column(Float, default=0.0)
    avg_view_percentage = Column(Float, default=0.0)
    likes = Column(Integer, default=0)
    subs_gained = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # One snapshot per video per day
    __table_args__ = (
        UniqueConstraint("video_id", "snapshot_date", name="uq_video_snapshot"),
    )
