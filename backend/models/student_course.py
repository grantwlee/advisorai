from database import Base
from sqlalchemy import Column, Integer, DateTime, ForeignKey, String
from sqlalchemy.orm import relationship


class StudentCourse(Base):
    __tablename__ = "student_courses"
    id = Column(Integer, primary_key=True)

    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False)
    status = Column(String(20), nullable=False, default="completed")
    term = Column(String(40))
    grade = Column(String(10))
    taken_at = Column(DateTime)

    student = relationship("Student", back_populates="course_records")
    course = relationship("Course", back_populates="student_records")
