from database import Base
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime

class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True)
    student_id = Column(String(20), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    program = Column(String(100), nullable=False)
    bulletin_year = Column(String(20), nullable=False)
    email = Column(String(120), unique=True, nullable=False)
    phone = Column(String(30), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
