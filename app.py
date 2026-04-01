import os
import sqlite3
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, g
from openai import OpenAI
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

app = Flask(__name__)
app.secret_key = "a_super_secret_flask_key_123"

# Database Setup
DATABASE = 'chatbot.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        db.commit()

init_db()

# ✅ HARD-CODED API KEY (PUT YOUR KEY HERE)
api_key = "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"

# ✅ OpenRouter Setup
if api_key.startswith("sk-or"):
    openai_client = OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1"
    )
    MODEL_NAME = "meta-llama/llama-3-8b-instruct"
    USING_OPENROUTER = True
else:
    openai_client = OpenAI(api_key=api_key)
    MODEL_NAME = "gpt-3.5-turbo"
    USING_OPENROUTER = False

print("✅ USING MODEL:", MODEL_NAME)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        
        db = get_db()
        existing_user = db.execute(
            'SELECT * FROM users WHERE username = ?', (username,)
        ).fetchone()
        
        if existing_user:
            return render_template("register.html", error="Username already exists.")
        
        db.execute(
            'INSERT INTO users (username, password) VALUES (?, ?)', 
            (username, generate_password_hash(password))
        )
        db.commit()
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        
        db = get_db()
        user = db.execute(
            'SELECT * FROM users WHERE username = ?', (username,)
        ).fetchone()
        
        if user and check_password_hash(user["password"], password):
            session['user_id'] = user["id"]
            session['username'] = user["username"]
            return redirect(url_for("index"))
        return render_template("login.html", error="Invalid credentials.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def index():
    return render_template("chat.html", username=session.get('username'))

@app.route("/api/history")
@login_required
def get_history():
    user_id = session.get("user_id")
    db = get_db()
    rows = db.execute(
        'SELECT role, content, timestamp FROM conversations WHERE user_id = ? ORDER BY timestamp ASC',
        (user_id,)
    ).fetchall()
    history = [
        {"role": row["role"], "content": row["content"], "timestamp": row["timestamp"]}
        for row in rows
    ]
    return jsonify(history)

@app.route("/api/chat", methods=["POST"])
@login_required
def chat():
    data = request.json
    user_message = data.get("text")
    user_id = session.get("user_id")
    
    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    db = get_db()
    
    rows = db.execute(
        'SELECT role, content FROM conversations WHERE user_id = ? ORDER BY timestamp DESC LIMIT 10',
        (user_id,)
    ).fetchall()

    history = [{"role": row["role"], "content": row["content"]} for row in rows]
    history.reverse()
    
    messages = [
        {"role": "system", "content": "You are EVA Chatbot, a smart, friendly AI assistant. Keep replies clear and helpful."}
    ]

    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    # Save user message
    now = datetime.utcnow().isoformat()
    db.execute(
        'INSERT INTO conversations (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)',
        (user_id, 'user', user_message, now)
    )
    db.commit()

    try:
        response = openai_client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=0.7,
            extra_headers={
                "HTTP-Referer": "http://localhost:5000",
                "X-Title": "EVA Chatbot"
            } if USING_OPENROUTER else {}
        )

        ai_reply = response.choices[0].message.content

    except Exception as e:
        print("❌ FULL ERROR:", str(e))
        ai_reply = f"Error: {str(e)}"

    # Save AI reply
    now_ai = datetime.utcnow().isoformat()
    db.execute(
        'INSERT INTO conversations (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)',
        (user_id, 'assistant', ai_reply, now_ai)
    )
    db.commit()

    return jsonify({"reply": ai_reply})

if __name__ == "__main__":
    app.run(debug=True, port=5000)