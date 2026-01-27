from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
import os
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
            "name": s.name,
            "email": s.email
            } 
            for s in students]
        return jsonify(student_list)
    if request.method == "POST":
        data = request.json
        try:
            new_student = Student(id=data["id"],name=data["name"], email=data["email"])
            session.add(new_student)
            session.commit()
            #add more confirmation
            return jsonify({"id": new_student.id,
                            "name": new_student.name,
                            "email": new_student.email
                            }), 201
        except Exception as e:
            session.rollback()
            return jsonify({"error": str(e)}), 400
        
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

    print("Creating database tables...")
    Base.metadata.create_all(bind=session.get_bind())
    print("Database tables created.")   

    app.run(port=port, debug=True)