import os
import psycopg2
from psycopg2 import errors
from dotenv import load_dotenv

load_dotenv()


def get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", "5432")),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        dbname=os.getenv("DB_NAME"),
    )


INSERT_SQL = """
INSERT INTO bulletin_chunks
(bulletin_id, source_type, bulletin_year, program, section_title,
 page_number, chunk_index, chunk_hash, chunk_text)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (bulletin_id, chunk_hash) DO NOTHING;
"""


def insert_chunk(cur, row: tuple) -> bool:
    cur.execute(INSERT_SQL, row)
    # Postgres doesn't raise error because of ON CONFLICT
    return cur.rowcount == 1