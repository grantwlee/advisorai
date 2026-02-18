from flask import Flask, request, jsonify
from ingest.db.pg_writer import get_conn

app = Flask(__name__)


@app.get("/api/chunks/search")
def search():
    q = request.args.get("q", "").strip()

    if not q:
        return jsonify({"error": "q required"}), 400

    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id,
               bulletin_year,
               program,
               section_title,
               page_number,
               LEFT(chunk_text, 300) AS preview
        FROM bulletin_chunks
        WHERE to_tsvector('english', chunk_text)
              @@ plainto_tsquery('english', %s)
        LIMIT 25;
        """,
        (q,),
    )

    rows = cur.fetchall()

    # Convert tuples → dicts manually (psycopg2 doesn't auto-dict)
    columns = [desc[0] for desc in cur.description]
    results = [dict(zip(columns, row)) for row in rows]

    cur.close()
    conn.close()

    return jsonify({
        "q": q,
        "results": results
    })