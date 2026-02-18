from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
import os
from sqlalchemy import or_
from database import session, Base
from models import Student, Course, StudentCourse, AdvisingSession

load_dotenv()
FLASK_ENV = os.getenv("FLASK_ENV", "development")

app = Flask(__name__)
CORS(app)

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


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5001)) 

    #hosted on 0.0.0.0 because flask server needs to be accessible from outside the container when deployed with Docker
    app.run(host="0.0.0.0",port=port, debug=False)
