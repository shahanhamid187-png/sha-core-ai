import re
from pathlib import Path

from flask import Flask, render_template, request, jsonify, session, Response
from dotenv import load_dotenv
from google import genai
from google.genai import types, errors
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
import secrets
import sqlite3
import re
import requests
from gradio_client import Client

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



@app.route("/text-to-speech", methods=["POST"])
@limiter.limit("5 per minute")
def text_to_speech():
    data = request.get_json(silent=True) or {}
    text = data.get("text", "")
    language = data.get("language", "ur-PK")

    if not isinstance(text, str) or not text.strip():
        return jsonify({"error": "Text is required."}), 400

    if len(text) > 1000:
        return jsonify({"error": "Text is too long."}), 400

    if language != "ur-PK":
        return jsonify({"error": "Urdu voice is configured only."}), 400

    eleven_key = os.getenv("ELEVENLABS_API_KEY")
    if not eleven_key:
        return jsonify({"error": "ElevenLabs API key is missing from .env."}), 503

    voice_id = "RLxprZTuTXbMcc44BbWz"

    try:
        result = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            params={"output_format": "mp3_44100_128"},
            headers={
                "xi-api-key": eleven_key,
                "Content-Type": "application/json"
            },
            json={
                "text": text,
                "model_id": "eleven_v3",
                "voice_settings": {
                    "stability": 0.85,
                    "similarity_boost": 0.75,
                    "style": 0.0
                },
                "language_code": "ur"
            },
            timeout=60
        )

        if result.status_code != 200:
            print("ElevenLabs error:", result.status_code, result.text[:500])
            return jsonify({
                "error": "Voice generation failed. Check ElevenLabs key, voice access and credits."
            }), 502

        return Response(result.content, mimetype="audio/mpeg")

    except requests.RequestException as e:
        print("ElevenLabs connection error:", str(e))
        return jsonify({"error": "Could not connect to ElevenLabs."}), 502


@app.route("/generate-image", methods=["POST"])
@limiter.limit("3 per minute")
def generate_image():
    data = request.get_json(silent=True) or {}
    prompt = data.get("prompt", "")

    if not isinstance(prompt, str):
        return jsonify({"error": "Invalid prompt."}), 400

    prompt = prompt.strip()

    # SHA CORE AI - SMART NAME ART
    if not prompt or len(prompt) > 2048:
        return jsonify({"error": "Prompt must be between 1 and 2048 characters."}), 400

    name_to_render = None
    clean_prompt = " ".join(prompt.strip().split())

    name_patterns = [
        r"^(.+?)\s+name\s+ki\s+(?:(?:3d|4d)\s+)?(?:logo|pic|picture|image|wallpaper|art)$",
        r"^(.+?)\s+name\s+(?:logo|art|wallpaper)$",
        r"^(.+?)\s+(?:3d|4d)\s+logo$",
        r"^(?:create|make|generate)\s+(?:(?:a\s+)?(?:3d|4d)\s+)?(?:name\s+)?(?:logo|art|wallpaper)\s+(?:for|of)\s+(.+)$",
        r"^(?:(?:create|make|generate)\s+)?(?:(?:3d|4d)\s+)?(?:logo|art|wallpaper)\s+(?:for|of)\s+(.+)$"
    ]

    for index, pattern in enumerate(name_patterns):
        match = re.match(pattern, clean_prompt, re.IGNORECASE)
        if match:
            extracted = match.group(2) if index >= 3 else match.group(1)
            extracted = re.sub(r"[^A-Za-z0-9 '&.-]", "", extracted).strip(" .,!'-")
            if 1 <= len(extracted) <= 32:
                name_to_render = extracted.upper()
                break

    if name_to_render:
        prompt = (
            "Create a premium square luxury logo BACKGROUND only. "
            "Dark midnight navy background, elegant warm gold lighting, "
            "subtle cinematic glow, refined metallic atmosphere, "
            "balanced symmetrical composition, clean empty central space "
            "reserved for large typography to be added later. "
            "No letters, no words, no numbers, no symbols, no watermark, "
            "no people, no characters, no mascots, no unrelated objects. "
            "Professional international brand design."
        )

    if not prompt or len(prompt) > 2048:
        return jsonify({"error": "Prompt must be between 1 and 2048 characters."}), 400

    # SHA CORE AI - GEMINI IMAGE PROMPT ENHANCER
    if not name_to_render:
        try:
            prompt_response = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=(
                    "Create a professional, highly detailed English image-generation prompt. "
                    "Preserve the user's exact subject, setting, composition, style and mood. "
                    "For realistic image requests, aim for authentic professional photography: "
                    "natural lighting, physically accurate shadows, realistic materials, "
                    "fine natural textures, believable proportions and lifelike details. "
                    "Use plausible camera perspective, lens characteristics and depth of field. "
                    "Avoid artificial-looking skin, plastic textures, excessive smoothness, "
                    "oversharpening, fake reflections, distorted anatomy and exaggerated effects. "
                    "Do not add unnecessary objects, text, logos or watermarks. "
                    "Respect explicitly requested illustration or artistic styles. "
                    "Return only the final prompt, under 1200 characters.\n\n"
                    f"User request: {prompt}"
                ),
                config=types.GenerateContentConfig(
                    system_instruction=(
                        "You are SHA CORE AI's expert image prompt writer. "
                        "Understand Roman Urdu, Urdu and English. Preserve the user's intent accurately. "
                        "For photorealistic requests, describe genuine photography, natural light, "
                        "realistic textures, accurate shadows, believable details and natural colours. "
                        "Avoid the typical artificial AI-generated appearance. "
                        "Never force photorealism when the user explicitly requests an artistic style."
                    )
                )
            )

            enhanced_prompt = (prompt_response.text or "").strip()

            if enhanced_prompt:
                prompt = enhanced_prompt[:1800]

        except Exception as prompt_error:
            print("Gemini image prompt enhancement warning:", str(prompt_error))
    import base64

    image_mime = "image/png"

    try:
        minimax_client = Client("MiniMaxAI/minimax-h3-image")

        result = minimax_client.predict(
            prompt=prompt,
            images=[],
            aspect="1:1",
            resolution="4 MP",
            seed=0,
            randomize=True,
            enhance=True,
            reasoning_effort="low",
            api_name="/generate"
        )

        image_path = result[0] if isinstance(result, (tuple, list)) else result
        image_file = Path(image_path)

        if not image_file.is_file():
            raise FileNotFoundError("MiniMax did not return a valid image file.")

        image_bytes = image_file.read_bytes()
        image_mime = "image/png" if image_file.suffix.lower() == ".png" else "image/jpeg"
        image_data = base64.b64encode(image_bytes).decode("ascii")

    except Exception as generation_error:
        print("MiniMax image generation error:", str(generation_error))
        return jsonify({"error": "MiniMax image generation failed. Please try again."}), 502

    # Add the exact requested name after AI creates the background.
    # This prevents the image model from changing the spelling.
    if name_to_render:
        try:
            import base64
            import io
            from PIL import Image, ImageDraw, ImageFont, ImageFilter

            raw_image = base64.b64decode(image_data)
            canvas = Image.open(io.BytesIO(raw_image)).convert("RGBA")
            width, height = canvas.size

            font_paths = [
                r"C:\\Windows\\Fonts\\arialbd.ttf",
                r"C:\\Windows\\Fonts\seguisb.ttf",
                r"C:\\Windows\\Fonts\\bahnschrift.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            ]

            font = None
            font_size = int(min(width * 0.18, height * 0.22))

            for font_path in font_paths:
                if Path(font_path).exists():
                    font = ImageFont.truetype(font_path, font_size)
                    break

            if font is None:
                font = ImageFont.load_default()

            measure = ImageDraw.Draw(canvas)
            while font_size > 12:
                bounds = measure.textbbox((0, 0), name_to_render, font=font)
                text_width = bounds[2] - bounds[0]
                if text_width <= width * 0.84:
                    break
                font_size -= 2
                for font_path in font_paths:
                    if Path(font_path).exists():
                        font = ImageFont.truetype(font_path, font_size)
                        break

            bounds = measure.textbbox((0, 0), name_to_render, font=font, stroke_width=2)
            text_width = bounds[2] - bounds[0]
            text_height = bounds[3] - bounds[1]
            x = (width - text_width) // 2 - bounds[0]
            y = (height - text_height) // 2 - bounds[1]

            # Soft golden glow
            glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            glow_draw = ImageDraw.Draw(glow)
            glow_draw.text((x, y), name_to_render, font=font,
                           fill=(255, 190, 55, 210))
            glow = glow.filter(ImageFilter.GaussianBlur(max(5, width // 55)))
            canvas = Image.alpha_composite(canvas, glow)

            draw = ImageDraw.Draw(canvas)

            # Metallic depth / 3D extrusion
            for offset in range(9, 0, -1):
                draw.text((x + offset, y + offset), name_to_render,
                          font=font, fill=(95, 54, 12, 255),
                          stroke_width=2, stroke_fill=(45, 28, 12, 255))

            # Main gold lettering
            draw.text((x, y), name_to_render, font=font,
                      fill=(255, 220, 145, 255),
                      stroke_width=2, stroke_fill=(105, 66, 20, 255))

            output = io.BytesIO()
            canvas.convert("RGB").save(output, format="JPEG", quality=94)
            image_data = base64.b64encode(output.getvalue()).decode("ascii")
            image_mime = "image/jpeg"

        except Exception as overlay_error:
            print("Typography overlay warning:", str(overlay_error))

    return jsonify({
        "image": f"data:{image_mime};base64,{image_data}"
    })


create_database()
if __name__ == "__main__":
    app.run(debug=False)









