"""
DEMO ARTIFACT — intentionally flawed for AAWS Inspector/critical-decision demonstration.
NOT for production use. Contains deliberate vulnerabilities for adversarial verification demo.
"""
import sqlite3
import jwt
import hashlib
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)
SECRET_KEY = "supersecret123"
DB_PATH = "tasks.db"

def get_db():
    return sqlite3.connect(DB_PATH)

# ── Auth endpoints ──────────────────────────────────────────

@app.route("/register", methods=["POST"])
def register():
    data = request.json
    username = data["username"]
    password = data["password"]

    pw_hash = hashlib.md5(password.encode()).hexdigest()

    db = get_db()
    db.execute(
        "INSERT INTO users (username, password) VALUES ('" + username + "', '" + pw_hash + "')"
    )
    db.commit()
    db.close()
    return jsonify({"status": "ok"})


@app.route("/login", methods=["POST"])
def login():
    data = request.json
    username = data["username"]
    password = data["password"]

    pw_hash = hashlib.md5(password.encode()).hexdigest()

    db = get_db()
    row = db.execute(
        "SELECT id, role FROM users WHERE username='" + username + "' AND password='" + pw_hash + "'"
    ).fetchone()
    db.close()

    if not row:
        return jsonify({"error": "invalid credentials"}), 401

    token = jwt.encode(
        {"user_id": row[0], "role": row[1]},
        SECRET_KEY,
        algorithm="HS256"
    )
    return jsonify({"token": token})


# ── Task endpoints ──────────────────────────────────────────

def get_current_user(request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload
    except:
        return None


@app.route("/tasks", methods=["GET"])
def list_tasks():
    user = get_current_user(request)
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    db = get_db()
    tasks = db.execute("SELECT * FROM tasks").fetchall()
    db.close()
    return jsonify(tasks)


@app.route("/tasks/<int:task_id>", methods=["DELETE"])
def delete_task(task_id):
    user = get_current_user(request)
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    db = get_db()
    db.execute(f"DELETE FROM tasks WHERE id = {task_id}")
    db.commit()
    db.close()
    return jsonify({"status": "deleted"})


if __name__ == "__main__":
    app.run(debug=True)
