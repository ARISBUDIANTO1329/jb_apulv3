from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func
from app.models.base import Base


class AutoSeamlessProgress(Base):
    __tablename__ = "auto_seamless_progresses"

    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, nullable=False, index=True)
    raw_filename = Column(String(500), nullable=True)
    input_path = Column(String(1000), nullable=True)
    output_path = Column(String(1000), nullable=True)
    progress = Column(Integer, default=0)
    status = Column(String(50), default="pending")  # pending, processing, done, failed
    message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
