from database import Base
from sqlalchemy import Column, Integer, String

class Course(Base):
    __tablename__ = "courses"

    id = Column(Integer, primary_key=True)
    code = Column(String(20), nullable=False)
    title = Column(String(255), nullable=False)
    credits = Column(Integer, nullable=False)