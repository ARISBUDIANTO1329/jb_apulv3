from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, JSON
from sqlalchemy.sql import func
from app.models.base import Base


class AutoProductionSchedule(Base):
    __tablename__ = "auto_production_schedules"

    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, nullable=True, index=True)
    target = Column(String(50), nullable=False)  # upload_regular, livestream, production_daily
    workflow = Column(String(50), nullable=False)  # static, dynamic, final_production
    schedule_time = Column(String(10), nullable=True)  # HH:MM:SS
    start_mode = Column(String(20), default="today")  # today, tomorrow
    is_active = Column(Boolean, default=True)
    config_json = Column(JSON, nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
