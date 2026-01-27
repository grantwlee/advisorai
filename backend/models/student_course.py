from database import Base
from sqlalchemy import Column, Integer, DateTime, ForeignKey

class StudentCourse(Base):
    __tablename__ = "student_courses"
    id = Column(Integer, primary_key=True)

    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False)

    taken_at = Column(DateTime)