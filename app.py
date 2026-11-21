
from flask import Flask, render_template, request, jsonify, session
from dotenv import load_dotenv
from google import genai
from google.genai import types, errors
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
import secrets
import sqlite3

load_dotenv()

app = Flask(__name__)

# API Rate Limiting
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://"
)

app.secret_key = os.getenv("FLASK_SECRET_KEY")
app.config["SESSION_COOKIE_NAME"] = "sha_core_session"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

if not app.secret_key:
    raise RuntimeError("FLASK_SECRET_KEY is missing from .env")

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise RuntimeError("GEMINI_API_KEY is missing from .env")

client = genai.Client(api_key=api_key)


def get_db():
    connection = sqlite3.connect("sha_core.db")
    connection.row_factory = sqlite3.Row
    return connection


def get_owner_id():
    if "owner_id" not in session:
        session["owner_id"] = secrets.token_urlsafe(32)
    return session["owner_id"]


def create_database():
    connection = get_db()

    connection.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (chat_id) REFERENCES chats(id)
        )
    """)

    columns = [
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(chats)"
        ).fetchall()
    ]

    if "owner_id" not in columns:
        connection.execute(
            "ALTER TABLE chats ADD COLUMN owner_id TEXT"
        )

    connection.commit()
    connection.close()


@app.route("/")
def home():
    get_owner_id()
    return render_template("index.html")


@app.route("/history", methods=["GET"])
def get_history():
    owner_id = get_owner_id()
    connection = get_db()

    chats = connection.execute(
        "SELECT id, title FROM chats WHERE owner_id = ? ORDER BY id DESC",
        (owner_id,)
    ).fetchall()

    connection.close()

    return jsonify([
        {"id": chat["id"], "title": chat["title"]}
        for chat in chats
    ])


@app.route("/history/<int:chat_id>", methods=["GET"])
def open_history(chat_id):
    owner_id = get_owner_id()
    connection = get_db()

    chat = connection.execute(
        "SELECT id FROM chats WHERE id = ? AND owner_id = ?",
        (chat_id, owner_id)
    ).fetchone()

    if not chat:
        connection.close()
        return jsonify({"error": "Chat not found."}), 404

    messages = connection.execute(
        "SELECT role, content FROM messages WHERE chat_id = ? ORDER BY id",
        (chat_id,)
    ).fetchall()

    connection.close()
    session["chat_id"] = chat_id

    return jsonify([
        {"role": message["role"], "content": message["content"]}
        for message in messages
    ])


@app.route("/new-chat", methods=["POST"])
def new_chat():
    session.pop("chat_id", None)
    return jsonify({"success": True})


@app.route("/delete-chat/<int:chat_id>", methods=["DELETE"])
def delete_chat(chat_id):
    owner_id = get_owner_id()
    connection = get_db()

    chat = connection.execute(
        "SELECT id FROM chats WHERE id = ? AND owner_id = ?",
        (chat_id, owner_id)
    ).fetchone()

    if not chat:
        connection.close()
        return jsonify({"error": "Chat not found."}), 404

    connection.execute(
        "DELETE FROM messages WHERE chat_id = ?", (chat_id,)
    )

    connection.execute(
        "DELETE FROM chats WHERE id = ? AND owner_id = ?",
        (chat_id, owner_id)
    )

    connection.commit()
    connection.close()

    if session.get("chat_id") == chat_id:
        session.pop("chat_id", None)

    return jsonify({"success": True})


@app.route("/rename-chat/<int:chat_id>", methods=["POST"])
def rename_chat(chat_id):
    owner_id = get_owner_id()
    data = request.get_json(silent=True) or {}
    new_title = data.get("title", "").strip()

    if not new_title:
        return jsonify({"error": "Title cannot be empty."}), 400

    connection = get_db()

    cursor = connection.execute(
        "UPDATE chats SET title = ? WHERE id = ? AND owner_id = ?",
        (new_title[:50], chat_id, owner_id)
    )

    connection.commit()
    updated = cursor.rowcount
    connection.close()

    if updated == 0:
        return jsonify({"error": "Chat not found."}), 404

    return jsonify({"success": True})


@app.route("/chat", methods=["POST"])
@limiter.limit("10 per minute")
def chat():
    connection = None

    try:
        owner_id = get_owner_id()
        data = request.get_json(silent=True) or {}
        user_message = data.get("message", "").strip()

        if not user_message:
            return jsonify({"reply": "Please enter a message."}), 400

        if len(user_message) > 4000:
            return jsonify({"reply": "Message is too long."}), 400

        connection = get_db()
        chat_id = session.get("chat_id")

        if chat_id:
            existing_chat = connection.execute(
                "SELECT id FROM chats WHERE id = ? AND owner_id = ?",
                (chat_id, owner_id)
            ).fetchone()

            if not existing_chat:
                session.pop("chat_id", None)
                chat_id = None

        if not chat_id:
            cursor = connection.execute(
                "INSERT INTO chats (title, owner_id) VALUES (?, ?)",
                (user_message[:30], owner_id)
            )

            chat_id = cursor.lastrowid
            session["chat_id"] = chat_id
            connection.commit()

        saved_messages = connection.execute(
            """SELECT role, content FROM messages
               WHERE chat_id = ? ORDER BY id DESC LIMIT 20""",
            (chat_id,)
        ).fetchall()

        saved_messages = list(reversed(saved_messages))

        conversation = [
            types.Content(
                role=message["role"],
                parts=[types.Part.from_text(text=message["content"])]
            )
            for message in saved_messages
        ]

        conversation.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=user_message)]
            )
        )

        response = client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=conversation,
            config=types.GenerateContentConfig(
                system_instruction=(
                    "You are SHA CORE AI, created by Shahan Ali. "
                    "Shahan Ali created this application, not Gemini. "
                    "You use Google's Gemini technology."
                )
            )
        )

        reply = response.text or "I couldn't generate a response."

        connection.execute(
            "INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)",
            (chat_id, "user", user_message)
        )

        connection.execute(
            "INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)",
            (chat_id, "model", reply)
        )

        connection.commit()

        return jsonify({"reply": reply})

    except errors.APIError as e:
        print("AI API Error:", e)
        return jsonify({
            "reply": "SHA CORE AI is temporarily busy. Please try again."
        }), 503

    except Exception as e:
        print("Error:", e)
        return jsonify({
            "reply": "Something went wrong. Please try again."
        }), 500

    finally:
        if connection:
            connection.close()


create_database()

if __name__ == "__main__":
    app.run(debug=False)
