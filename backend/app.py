from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
import os
from sqlalchemy import or_
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from database import session, Base, engine
from models import Student, Course, StudentCourse, AdvisingSession
import faiss
from sentence_transformers import SentenceTransformer
import json
import numpy as np

load_dotenv()
FLASK_ENV = os.getenv("FLASK_ENV", "development")

app = Flask(__name__)
CORS(app)

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_PROCESSED_DIR = "data/bulletins/processed"
PROCESSED_DIR = os.getenv("RETRIEVAL_DATA_DIR", DEFAULT_PROCESSED_DIR)
FAISS_PATH = os.path.join(PROCESSED_DIR, "bulletin_index.faiss")
JSONL_PATH = os.path.join(PROCESSED_DIR, "bulletin_chunks.jsonl")

# Load once
model = SentenceTransformer(MODEL_NAME)
index = faiss.read_index(FAISS_PATH)

# Load metadata
with open(JSONL_PATH, "r") as f:
    metadata = [json.loads(line) for line in f]

print(f"Retrieval data loaded from {PROCESSED_DIR}")
print(f"FAISS index path: {FAISS_PATH}")
print(f"JSONL path: {JSONL_PATH}")
print(f"Metadata rows loaded: {len(metadata)}")

DB_DIALECT = engine.dialect.name.lower()
if DB_DIALECT != "postgresql":
    raise RuntimeError(f"Unsupported database dialect: {DB_DIALECT}. This backend is PostgreSQL-only.")

# Fast lookup for SQL results -> canonical chunk metadata from JSONL
metadata_by_hash = {row.get("hash"): row for row in metadata if row.get("hash")}


def semantic_search(q: str, k: int = 5) -> list[dict]:
    q_vec = model.encode([q], normalize_embeddings=True)
    scores, indices = index.search(np.array(q_vec, dtype=np.float32), k)

    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx == -1:
            continue

        row = metadata[idx]
        results.append({
            "chunkId": row["chunkId"],
            "bulletin": row["bulletin"],
            "pageOccurrence": row["pageOccurrence"],
            "preview": row["chunk"][:300],
            "semanticScore": float(score),
        })

    return results


def keyword_search_sql(q: str, k: int = 10) -> list[dict]:
    """
    PostgreSQL full-text search using to_tsvector/plainto_tsquery + ts_rank_cd.
    """
    sql = text(
        """
        SELECT
            chunk_hash,
            bulletin_year,
            chunk_text,
            ts_rank_cd(
                to_tsvector('english', chunk_text),
                plainto_tsquery('english', :q)
            ) AS keyword_score
        FROM bulletin_chunks
        WHERE to_tsvector('english', chunk_text) @@ plainto_tsquery('english', :q)
        ORDER BY keyword_score DESC
        LIMIT :k
        """
    )

    with engine.connect() as conn:
        rows = conn.execute(sql, {"q": q, "k": int(k)}).mappings().all()

    results = []
    for r in rows:
        hash_key = r.get("chunk_hash")
        meta = metadata_by_hash.get(hash_key)

        if meta:
            chunk_id = meta["chunkId"]
            bulletin = meta["bulletin"]
            page_occurrence = meta["pageOccurrence"]
            preview = meta["chunk"][:300]
        else:
            # Fallback if hash is not found in JSONL metadata
            bulletin = r.get("bulletin_year", "unknown")
            chunk_id = f"{bulletin}:{hash_key[:8] if hash_key else 'unknown'}"
            page_occurrence = []
            preview = (r.get("chunk_text") or "")[:300]

        results.append({
            "chunkId": chunk_id,
            "bulletin": bulletin,
            "pageOccurrence": page_occurrence,
            "preview": preview,
            "keywordScore": float(r.get("keyword_score") or 0.0),
        })

    return results

@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})

@app.route("/api/students", methods=["GET", "POST"])
def students():
    if request.method == "GET": 
        students = session.query(Student).all()
        student_list = [{
            "id": s.id,
            "student_id": s.student_id,
            "name": s.name,
            "program": s.program,
            "bulletin_year": s.bulletin_year,
            "email": s.email,
            "phone": s.phone,
            } 
            for s in students]
        return jsonify(student_list)
    if request.method == "POST":
        data = request.json or {}
        try:
            new_student = Student(
                student_id=data["student_id"],
                name=data["name"],
                program=data["program"],
                bulletin_year=data["bulletin_year"],
                email=data["email"],
                phone=data["phone"],
            )
            session.add(new_student)
            session.commit()
            return jsonify({
                "id": new_student.id,
                "student_id": new_student.student_id,
                "name": new_student.name,
                "program": new_student.program,
                "bulletin_year": new_student.bulletin_year,
                "email": new_student.email,
                "phone": new_student.phone,
            }), 201
        except Exception as e:
            session.rollback()
            return jsonify({"error": str(e)}), 400

@app.route("/api/students/search", methods=["GET"])
def students_search():
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify([])

    pattern = f"%{query}%"
    students = (
        session.query(Student)
        .filter(
            or_(
                Student.name.ilike(pattern),
                Student.student_id.ilike(pattern),
                Student.program.ilike(pattern),
            )
        )
        .limit(10)
        .all()
    )

    results = [{"student_id": s.student_id, "name": s.name} for s in students]
    return jsonify(results)

@app.route("/api/students/<student_id>", methods=["GET"])
def student_detail(student_id):
    student = session.query(Student).filter(Student.student_id == student_id).first()
    if not student:
        return jsonify({"error": "Student not found"}), 404

    return jsonify({
        "student_id": student.student_id,
        "name": student.name,
        "program": student.program,
        "bulletin_year": student.bulletin_year,
        "email": student.email,
        "phone": student.phone,
    })
        
@app.route("/api/courses", methods=["GET", "POST"])
def courses():
    if request.method == "GET": 
        courses = session.query(Course).all()
        course_list = [{
            "id": c.id,
            "code": c.code,
            "title": c.title,
            "credits": c.credits
            } 
            for c in courses]
        return jsonify(course_list)
    if request.method == "POST":
        data = request.json
        try:
            new_course = Course(id=data["id"],code=data["code"], title=data["title"], credits=data["credits"])
            session.add(new_course)
            session.commit()
            return jsonify({"id": new_course.id,
                            "code": new_course.code,
                            "title": new_course.title,
                            "credits": new_course.credits
                            }), 201
        except Exception as e:
            session.rollback()
            return jsonify({"error": str(e)}), 400
        
@app.route("/api/advising_sessions", methods=["GET", "POST"])
def advising_sessions():
    if request.method == "GET": 
        sessions = session.query(AdvisingSession).all()
        session_list = [{
            "id": s.id,
            "student_id": s.student_id,
            "notes": s.notes,
            "created_at": s.created_at.isoformat()
            } 
            for s in sessions]
        return jsonify(session_list)
    if request.method == "POST":
        data = request.json
        try:
            new_session = AdvisingSession(student_id=data["student_id"], notes=data["notes"])
            session.add(new_session)
            session.commit()
            return jsonify({"id": new_session.id,
                            "student_id": new_session.student_id,
                            "notes": new_session.notes,
                            "created_at": new_session.created_at.isoformat()
                            }), 201
        except Exception as e:
            session.rollback()
            return jsonify({"error": str(e)}), 400
        
@app.route("/api/student_courses", methods=["GET", "POST"])
def student_courses(): 
    if request.method == "GET": 
        scs = session.query(StudentCourse).all()
        sc_list = [{
            "id": sc.id,
            "student_id": sc.student_id,
            "course_id": sc.course_id,
            "taken_at": sc.taken_at.isoformat() if sc.taken_at else None
            } 
            for sc in scs]
        return jsonify(sc_list)
    if request.method == "POST":
        data = request.json
        try:
            new_sc = StudentCourse(student_id=data["student_id"], course_id=data["course_id"], taken_at=data.get("taken_at"))
            session.add(new_sc)
            session.commit()
            return jsonify({"id": new_sc.id,
                            "student_id": new_sc.student_id,
                            "course_id": new_sc.course_id,
                            "taken_at": new_sc.taken_at.isoformat() if new_sc.taken_at else None
                            }), 201
        except Exception as e:
            session.rollback()
            return jsonify({"error": str(e)}), 400

@app.get("/api/retrieve/semantic")
def retrieve_semantic():
    q = request.args.get("q", "").strip()
    k = int(request.args.get("k", 5))

    if not q:
        return jsonify({"error": "q required"}), 400

    semantic_results = semantic_search(q, k)
    results = []
    for row in semantic_results:
        results.append({
            "chunkId": row["chunkId"],
            "bulletin": row["bulletin"],
            "pageOccurrence": row["pageOccurrence"],
            "preview": row["preview"],
            "score": row["semanticScore"],
        })

    return jsonify({
        "query": q,
        "results": results
    })


@app.get("/api/retrieve/keyword")
def retrieve_keyword():
    q = request.args.get("q", "").strip()
    k = int(request.args.get("k", 5))

    if not q:
        return jsonify({"error": "q required"}), 400

    try:
        keyword_results = keyword_search_sql(q, k)
    except SQLAlchemyError as exc:
        return jsonify({
            "error": "Keyword retrieval failed. Ensure bulletin_chunks and FULLTEXT/FTS index exist.",
            "detail": str(exc),
        }), 500

    results = []
    for row in keyword_results:
        results.append({
            "chunkId": row["chunkId"],
            "bulletin": row["bulletin"],
            "pageOccurrence": row["pageOccurrence"],
            "preview": row["preview"],
            "score": row["keywordScore"],
        })

    return jsonify({
        "query": q,
        "results": results
    })


@app.get("/api/retrieve")
def retrieve_hybrid():
    q = request.args.get("q", "").strip()

    if not q:
        return jsonify({"error": "q required"}), 400

    semantic_top = semantic_search(q, 10)

    try:
        keyword_top = keyword_search_sql(q, 10)
    except SQLAlchemyError as exc:
        return jsonify({
            "error": "Hybrid retrieval failed in keyword step. Ensure bulletin_chunks and FULLTEXT/FTS index exist.",
            "detail": str(exc),
        }), 500

    merged: dict[str, dict] = {}

    # Seed with semantic results
    for r in semantic_top:
        merged[r["chunkId"]] = {
            "chunkId": r["chunkId"],
            "bulletin": r["bulletin"],
            "pageOccurrence": r["pageOccurrence"],
            "preview": r["preview"],
            "semanticScore": r["semanticScore"],
            "keywordMatched": False,
        }

    # Merge keyword hits
    for r in keyword_top:
        cid = r["chunkId"]
        if cid not in merged:
            merged[cid] = {
                "chunkId": r["chunkId"],
                "bulletin": r["bulletin"],
                "pageOccurrence": r["pageOccurrence"],
                "preview": r["preview"],
                "semanticScore": 0.0,
                "keywordMatched": True,
            }
        else:
            merged[cid]["keywordMatched"] = True

    # Required scoring model:
    # totalScore = semantic similarity + 2 (if keyword match)
    results = []
    for row in merged.values():
        total_score = float(row["semanticScore"]) + (2.0 if row["keywordMatched"] else 0.0)
        results.append({
            "chunkId": row["chunkId"],
            "bulletin": row["bulletin"],
            "pageOccurrence": row["pageOccurrence"],
            "score": round(total_score, 6),
            "preview": row["preview"],
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    results = results[:5]

    return jsonify({
        "query": q,
        "results": results
    })
    

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5001)) 

    #hosted on 0.0.0.0 because flask server needs to be accessible from outside the container when deployed with Docker
    app.run(host="0.0.0.0",port=port, debug=False)
