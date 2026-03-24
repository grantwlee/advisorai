from datetime import datetime

from sqlalchemy import select

from database import session
from models import Course, Student, StudentCourse


def normalize_status(status: str | None) -> str:
    normalized = (status or "completed").strip().lower().replace(" ", "_")
    valid = {"completed", "in_progress", "planned", "transfer", "waived"}
    return normalized if normalized in valid else "completed"


def serialize_course(course: Course) -> dict:
    return {
        "id": course.id,
        "code": course.code,
        "title": course.title,
        "credits": course.credits,
    }


def serialize_student_course(row: StudentCourse) -> dict:
    return {
        "id": row.id,
        "status": row.status,
        "term": row.term,
        "grade": row.grade,
        "taken_at": row.taken_at.isoformat() if row.taken_at else None,
        "course": serialize_course(row.course),
    }


def serialize_student(student: Student, include_courses: bool = True) -> dict:
    payload = {
        "id": student.id,
        "student_id": student.student_id,
        "name": student.name,
        "program": student.program,
        "bulletin_year": student.bulletin_year,
        "email": student.email,
        "phone": student.phone,
    }
    if include_courses:
        payload["courses"] = [
            serialize_student_course(row)
            for row in sorted(
                student.course_records,
                key=lambda item: ((item.course.code if item.course else ""), item.id),
            )
        ]
    return payload


def get_student(student_identifier: str) -> Student | None:
    return (
        session.query(Student)
        .filter(Student.student_id == student_identifier)
        .first()
    )


def get_student_payload(student_identifier: str) -> dict | None:
    student = get_student(student_identifier)
    if not student:
        return None
    return serialize_student(student, include_courses=True)


def resolve_course(data: dict) -> Course:
    course_id = data.get("course_id")
    course_code = (data.get("course_code") or "").strip()
    course = None
    if course_id:
        course = session.query(Course).filter(Course.id == course_id).first()
    elif course_code:
        course = session.query(Course).filter(Course.code == course_code).first()

    if course:
        return course

    if not course_code:
        raise ValueError("course_id or course_code is required")

    course = Course(
        code=course_code,
        title=(data.get("title") or course_code).strip(),
        credits=int(data.get("credits") or 3),
    )
    session.add(course)
    session.flush()
    return course


def add_or_update_student_course(student_identifier: str, data: dict) -> dict:
    student = get_student(student_identifier)
    if not student:
        raise ValueError("Student not found")

    course = resolve_course(data)
    status = normalize_status(data.get("status"))

    existing = (
        session.query(StudentCourse)
        .filter(
            StudentCourse.student_id == student.id,
            StudentCourse.course_id == course.id,
        )
        .first()
    )

    if existing:
        existing.status = status
        existing.term = data.get("term")
        existing.grade = data.get("grade")
        existing.taken_at = _parse_taken_at(data.get("taken_at"))
        session.commit()
        session.refresh(existing)
        return serialize_student_course(existing)

    record = StudentCourse(
        student_id=student.id,
        course_id=course.id,
        status=status,
        term=data.get("term"),
        grade=data.get("grade"),
        taken_at=_parse_taken_at(data.get("taken_at")),
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return serialize_student_course(record)


def delete_student_course(student_identifier: str, record_id: int) -> bool:
    student = get_student(student_identifier)
    if not student:
        return False

    record = (
        session.query(StudentCourse)
        .filter(
            StudentCourse.id == record_id,
            StudentCourse.student_id == student.id,
        )
        .first()
    )
    if not record:
        return False

    session.delete(record)
    session.commit()
    return True


def _parse_taken_at(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
