from sqlalchemy import text

from database import Base, engine


def ensure_runtime_schema() -> None:
    Base.metadata.create_all(bind=engine)

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                ALTER TABLE student_courses
                ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'completed'
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE student_courses
                ADD COLUMN IF NOT EXISTS term VARCHAR(40)
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE student_courses
                ADD COLUMN IF NOT EXISTS grade VARCHAR(10)
                """
            )
        )
        conn.execute(
            text(
                """
                UPDATE student_courses
                SET status = 'completed'
                WHERE status IS NULL
                """
            )
        )
