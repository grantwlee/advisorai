import os
from dotenv import load_dotenv
from database import Base, session
# Import all models so they register with SQLAlchemy metadata
import models  # noqa: F401
from models import Student

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


def create_tables() -> None:
    Base.metadata.create_all(bind=session.get_bind())


def seed_students() -> int:
    created = 0
    for data in SEED_STUDENTS:
        exists = (
            session.query(Student)
            .filter(Student.student_id == data["student_id"])
            .first()
        )
        if exists:
            continue
        session.add(Student(**data))
        created += 1
    if created:
        session.commit()
    return created


def main() -> None:
    print("Creating database tables...")
    create_tables()
    print("Tables ready.")
    created = seed_students()
    print(f"Seeded {created} students.")


if __name__ == "__main__":
    main()
