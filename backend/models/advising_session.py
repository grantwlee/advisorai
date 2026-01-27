from datetime import datetime
from database import Base
from sqlalchemy import Column, Integer, ForeignKey, Text, DateTime

class AdvisingSession(Base):
    __tablename__ = "advising_sessions"

    id = Column(Integer, primary_key=True)

    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)

    notes = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)