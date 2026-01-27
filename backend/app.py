from flask import Flask, jsonify
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

@app.route("/api/students")
def get_students():
    students = session.execute("SELECT * FROM students").fetchall()
    student_list = [{"id": s.id, "name": s.name, "email": s.email} for s in students]
    return jsonify(student_list)


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5001))

    print("Creating database tables...")
    Base.metadata.create_all(bind=session.get_bind())
    print("Database tables created.")   

    app.run(port=port, debug=True)