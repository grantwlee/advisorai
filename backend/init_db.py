from dotenv import load_dotenv

import models  # noqa: F401
from database import session
from models import Course, Student, StudentCourse
from services.profile_service import normalize_status
from services.runtime_setup import ensure_runtime_schema

load_dotenv()


SEED_STUDENTS = [
    {
        "student_id": "S1001",
        "name": "Alex Johnson",
        "program": "Computer Science",
        "bulletin_year": "2023-2024",
        "email": "alex@example.com",
        "phone": "555-0101",
    },
    {
        "student_id": "S1002",
        "name": "Maria Lopez",
        "program": "Information Systems",
        "bulletin_year": "2022-2023",
        "email": "maria@example.com",
        "phone": "555-0102",
    },
    {
        "student_id": "S1003",
        "name": "Daniel Kim",
        "program": "Computer Science",
        "bulletin_year": "2023-2024",
        "email": "daniel@example.com",
        "phone": "555-0103",
    },
    {
        "student_id": "S1004",
        "name": "Sarah Ahmed",
        "program": "Business Analytics",
        "bulletin_year": "2021-2022",
        "email": "sarah@example.com",
        "phone": "555-0104",
    },
    {
        "student_id": "S1005",
        "name": "Alyssa Carter",
        "program": "Computer Science",
        "bulletin_year": "2022-2023",
        "email": "alyssa@example.com",
        "phone": "555-0105",
    },
    {
        "student_id": "S1006",
        "name": "Michael Chen",
        "program": "Information Systems",
        "bulletin_year": "2023-2024",
        "email": "michael@example.com",
        "phone": "555-0106",
    },
]

SEED_COURSES = [
    ("CPTR 151", "Computer Science I", 3),
    ("CPTR 152", "Computer Science II", 3),
    ("CPTR 230", "Data Science Fundamentals", 3),
    ("CPTR 276", "Data Structures and Algorithms", 3),
    ("CPTR 425", "Programming Languages", 3),
    ("CPTR 430", "Analysis of Algorithms", 3),
    ("CPTR 437", "Formal Theory of Computation", 3),
    ("CPTR 440", "Operating Systems", 3),
    ("CPTR 460", "Software Engineering", 3),
    ("CPTR 487", "Artificial Intelligence", 3),
    ("INFS 226", "Hardware and Software", 3),
    ("INFS 235", "Business Programming", 3),
    ("INFS 310", "Networks and Telecommunications", 3),
    ("INFS 318", "Business Systems Analysis and Design", 3),
    ("INFS 428", "Database Systems Design and Development", 3),
]

SEED_STUDENT_COURSES = {
    "S1001": [
        {"course_code": "CPTR 151", "status": "completed", "grade": "A"},
        {"course_code": "CPTR 152", "status": "completed", "grade": "A-"},
        {"course_code": "CPTR 230", "status": "completed", "grade": "B+"},
        {"course_code": "CPTR 276", "status": "in_progress", "term": "Spring 2026"},
    ],
    "S1002": [
        {"course_code": "CPTR 151", "status": "completed", "grade": "B"},
        {"course_code": "INFS 226", "status": "completed", "grade": "A-"},
        {"course_code": "INFS 235", "status": "in_progress", "term": "Spring 2026"},
    ],
    "S1003": [
        {"course_code": "CPTR 151", "status": "completed", "grade": "A"},
        {"course_code": "CPTR 152", "status": "completed", "grade": "B+"},
    ],
}


def seed_students() -> int:
    created = 0
    for data in SEED_STUDENTS:
        exists = session.query(Student).filter(Student.student_id == data["student_id"]).first()
        if exists:
            continue
        session.add(Student(**data))
        created += 1
    if created:
        session.commit()
    return created


def seed_courses() -> int:
    created = 0
    for code, title, credits in SEED_COURSES:
        exists = session.query(Course).filter(Course.code == code).first()
        if exists:
            continue
        session.add(Course(code=code, title=title, credits=credits))
        created += 1
    if created:
        session.commit()
    return created


def seed_student_courses() -> int:
    created = 0
    for student_external_id, rows in SEED_STUDENT_COURSES.items():
        student = session.query(Student).filter(Student.student_id == student_external_id).first()
        if not student:
            continue
        for row in rows:
            course = session.query(Course).filter(Course.code == row["course_code"]).first()
            if not course:
                continue
            exists = (
                session.query(StudentCourse)
                .filter(
                    StudentCourse.student_id == student.id,
                    StudentCourse.course_id == course.id,
                )
                .first()
            )
            if exists:
                exists.status = normalize_status(row.get("status"))
                exists.term = row.get("term")
                exists.grade = row.get("grade")
                continue

            session.add(
                StudentCourse(
                    student_id=student.id,
                    course_id=course.id,
                    status=normalize_status(row.get("status")),
                    term=row.get("term"),
                    grade=row.get("grade"),
                )
            )
            created += 1
    session.commit()
    return created


def main() -> None:
    print("Ensuring database schema...")
    ensure_runtime_schema()
    print("Schema ready.")
    seeded_students = seed_students()
    seeded_courses = seed_courses()
    seeded_student_courses = seed_student_courses()
    print(f"Seeded {seeded_students} students.")
    print(f"Seeded {seeded_courses} courses.")
    print(f"Seeded {seeded_student_courses} student course records.")


if __name__ == "__main__":
    main()
