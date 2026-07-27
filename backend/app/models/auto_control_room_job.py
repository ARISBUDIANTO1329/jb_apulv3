from sqlalchemy import Column, Integer, String, Text, DateTime, JSON
from sqlalchemy.sql import func
from app.models.base import Base


class AutoControlRoomJob(Base):
    __tablename__ = "auto_control_room_jobs"

    id = Column(Integer, primary_key=True, index=True)
    auto_production_schedule_id = Column(Integer, nullable=True, index=True)
    channel_id = Column(Integer, nullable=True, index=True)
    target = Column(String(50), nullable=True)
    workflow = Column(String(50), nullable=True)
    run_date = Column(String(20), nullable=True)
    status = Column(String(50), default="waiting")  # waiting, blocked, running, done, failed
    current_stage = Column(String(100), default="pending_activation")
    progress = Column(Integer, default=0)
    total_items = Column(Integer, default=0)
    done_items = Column(Integer, default=0)
    current_item_order = Column(Integer, nullable=True)
    config_json = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AutoControlRoomJobItem(Base):
    __tablename__ = "auto_control_room_job_items"

    id = Column(Integer, primary_key=True, index=True)
    auto_control_room_job_id = Column(Integer, nullable=False, index=True)
    queue_order = Column(Integer, default=0)
    target = Column(String(50), nullable=True)
    workflow = Column(String(50), nullable=True)
    source_type = Column(String(100), nullable=True)
    status = Column(String(50), default="waiting")
    current_stage = Column(String(100), default="waiting")
    progress = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
