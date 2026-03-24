import os
import traceback

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError

from database import engine, session
from models import AdvisingSession, Course, Student, StudentCourse
from services.llm_client import LLMError, OllamaClient
from services.profile_service import (
    add_or_update_student_course,
    delete_student_course,
    get_student,
    get_student_payload,
    serialize_course,
    serialize_student,
    serialize_student_course,
)
from services.query_service import QueryService
from services.retrieval_service import get_retrieval_service
from services.runtime_setup import ensure_runtime_schema

load_dotenv()

FLASK_ENV = os.getenv("FLASK_ENV", "development")
PORT = int(os.getenv("PORT", 5001))

app = Flask(__name__)
CORS(app)

ensure_runtime_schema()

DB_DIALECT = engine.dialect.name.lower()
if DB_DIALECT != "postgresql":
    raise RuntimeError(
        f"Unsupported database dialect: {DB_DIALECT}. This backend is PostgreSQL-only."
    )

retrieval_service = get_retrieval_service()
query_service = QueryService()
llm_client = OllamaClient()


def serialize_retrieval_result(row: dict) -> dict:
    return {
        "chunkId": row["chunkId"],
        "bulletin": row["bulletin"],
        "pageOccurrence": row.get("pageOccurrence") or [],
        "preview": row["preview"],
        "score": row.get("score", row.get("semanticScore", row.get("keywordScore", 0.0))),
        "sourcePdf": row.get("sourcePdf"),
    }


@app.route("/api/health")
def health():
    llm_status = {"status": "unknown", "base_url": llm_client.base_url, "model": llm_client.model}
    try:
        tags = llm_client.health()
        llm_status["status"] = "reachable"
        llm_status["models"] = [row.get("name") for row in tags.get("models", [])]
    except LLMError as exc:
        llm_status["status"] = "unreachable"
        llm_status["detail"] = str(exc)

    return jsonify(
        {
            "status": "ok",
            "environment": FLASK_ENV,
            "retrieval": {
                "processed_dir": retrieval_service.processed_dir,
                "chunks_loaded": len(retrieval_service.metadata),
            },
            "llm": llm_status,
        }
    )


@app.route("/api/llm/health")
def llm_health():
    try:
        return jsonify(llm_client.health())
    except LLMError as exc:
        return jsonify({"status": "error", "detail": str(exc)}), 503


@app.route("/api/students", methods=["GET", "POST"])
def students():
    if request.method == "GET":
        students = session.query(Student).all()
        return jsonify([serialize_student(student, include_courses=False) for student in students])

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
        return jsonify(serialize_student(new_student, include_courses=False)), 201
    except Exception as exc:
        session.rollback()
        return jsonify({"error": str(exc)}), 400


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
    return jsonify(
        [
            {
                "student_id": student.student_id,
                "name": student.name,
                "program": student.program,
                "bulletin_year": student.bulletin_year,
            }
            for student in students
        ]
    )


@app.route("/api/students/<student_id>", methods=["GET"])
def student_detail(student_id):
    payload = get_student_payload(student_id)
    if not payload:
        return jsonify({"error": "Student not found"}), 404
    return jsonify(payload)


@app.route("/api/students/<student_id>/courses", methods=["GET", "POST"])
def student_courses_for_student(student_id):
    if request.method == "GET":
        payload = get_student_payload(student_id)
        if not payload:
            return jsonify({"error": "Student not found"}), 404
        return jsonify(payload.get("courses", []))

    data = request.json or {}
    try:
        record = add_or_update_student_course(student_id, data)
        return jsonify(record), 201
    except ValueError as exc:
        session.rollback()
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        session.rollback()
        return jsonify({"error": str(exc)}), 500


@app.route("/api/students/<student_id>/courses/<int:record_id>", methods=["DELETE"])
def student_course_delete(student_id, record_id):
    deleted = delete_student_course(student_id, record_id)
    if not deleted:
        return jsonify({"error": "Student course record not found"}), 404
    return jsonify({"status": "deleted", "id": record_id})


@app.route("/api/courses", methods=["GET", "POST"])
def courses():
    if request.method == "GET":
        rows = session.query(Course).order_by(Course.code).all()
        return jsonify([serialize_course(course) for course in rows])

    data = request.json or {}
    try:
        course = Course(
            code=data["code"],
            title=data["title"],
            credits=int(data["credits"]),
        )
        session.add(course)
        session.commit()
        return jsonify(serialize_course(course)), 201
    except Exception as exc:
        session.rollback()
        return jsonify({"error": str(exc)}), 400


@app.route("/api/advising_sessions", methods=["GET", "POST"])
def advising_sessions():
    if request.method == "GET":
        rows = session.query(AdvisingSession).all()
        return jsonify(
            [
                {
                    "id": row.id,
                    "student_id": row.student_id,
                    "notes": row.notes,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]
        )

    data = request.json or {}
    try:
        record = AdvisingSession(student_id=data["student_id"], notes=data["notes"])
        session.add(record)
        session.commit()
        return (
            jsonify(
                {
                    "id": record.id,
                    "student_id": record.student_id,
                    "notes": record.notes,
                    "created_at": record.created_at.isoformat(),
                }
            ),
            201,
        )
    except Exception as exc:
        session.rollback()
        return jsonify({"error": str(exc)}), 400


@app.route("/api/student_courses", methods=["GET", "POST"])
def student_courses():
    if request.method == "GET":
        rows = session.query(StudentCourse).all()
        return jsonify([serialize_student_course(row) for row in rows])

    data = request.json or {}
    student = session.query(Student).filter(Student.id == data.get("student_id")).first()
    if not student:
        return jsonify({"error": "Student not found"}), 404

    try:
        record = add_or_update_student_course(
            student.student_id,
            {
                "course_id": data.get("course_id"),
                "course_code": data.get("course_code"),
                "status": data.get("status"),
                "term": data.get("term"),
                "grade": data.get("grade"),
                "taken_at": data.get("taken_at"),
            },
        )
        return jsonify(record), 201
    except ValueError as exc:
        session.rollback()
        return jsonify({"error": str(exc)}), 400


@app.get("/api/retrieve/semantic")
def retrieve_semantic():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "q required"}), 400

    k = int(request.args.get("k", 5))
    bulletin_year = request.args.get("bulletin_year")
    program = request.args.get("program")
    results = retrieval_service.semantic_search(
        query,
        k=k,
        bulletin_year=bulletin_year,
        program=program,
    )
    return jsonify({"query": query, "results": [serialize_retrieval_result(row) for row in results]})


@app.get("/api/retrieve/keyword")
def retrieve_keyword():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "q required"}), 400

    k = int(request.args.get("k", 5))
    bulletin_year = request.args.get("bulletin_year")
    program = request.args.get("program")
    try:
        results = retrieval_service.keyword_search(
            query,
            k=k,
            bulletin_year=bulletin_year,
            program=program,
        )
    except SQLAlchemyError as exc:
        return jsonify(
            {
                "error": "Keyword retrieval failed. Ensure bulletin_chunks and FTS index exist.",
                "detail": str(exc),
            }
        ), 500

    return jsonify({"query": query, "results": [serialize_retrieval_result(row) for row in results]})


@app.get("/api/retrieve")
def retrieve_hybrid():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "q required"}), 400

    k = int(request.args.get("k", 5))
    bulletin_year = request.args.get("bulletin_year")
    program = request.args.get("program")
    try:
        results = retrieval_service.hybrid_search(
            query,
            k=k,
            bulletin_year=bulletin_year,
            program=program,
        )
    except SQLAlchemyError as exc:
        return jsonify(
            {
                "error": "Hybrid retrieval failed in keyword step. Ensure bulletin_chunks and FTS index exist.",
                "detail": str(exc),
            }
        ), 500

    return jsonify({"query": query, "results": [serialize_retrieval_result(row) for row in results]})


@app.post("/api/query")
def query():
    data = request.json or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "question is required"}), 400

    top_k = int(data.get("top_k") or 5)
    student_id = data.get("student_id")
    if student_id and not get_student(student_id):
        return jsonify({"error": "Student not found"}), 404

    try:
        response = query_service.answer_question(
            question=question,
            student_id=student_id,
            top_k=top_k,
        )
        return jsonify(response)
    except SQLAlchemyError as exc:
        session.rollback()
        return jsonify(
            {
                "error": "Query retrieval failed. Ensure bulletin_chunks are loaded and the retrieval index is available.",
                "detail": str(exc),
            }
        ), 500
    except Exception as exc:
        session.rollback()
        traceback.print_exc()
        return jsonify(
            {
                "error": str(exc),
                "type": exc.__class__.__name__,
            }
        ), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
