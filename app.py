from flask import Flask, render_template, request, Response, jsonify
from flask import stream_with_context, session
from datetime import timedelta
import requests
import sqlite3 , re
import json
import base64

app = Flask(__name__)
# 🔥 AUTO CREATE DATABASE
def init_db():
    conn = get_db_connection()
    c = conn.cursor()

    # Users table (Updated for SecureRepair integration)
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        email TEXT UNIQUE,
        mobile TEXT,
        password TEXT
    )
    """)

    # Chats table
    c.execute("""
    CREATE TABLE IF NOT EXISTS chats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        message TEXT,
        response TEXT
    )
    """)

    conn.commit()
    conn.close()
app.secret_key = "secret123"   # 🔥 REQUIRED for session
app.permanent_session_lifetime = timedelta(minutes=10)


# 🚦 Traffic keywords
TRAFFIC_KEYWORDS = [
    "traffic", "signal", "road", "helmet",
    "accident", "rules", "driving", "speed", "lane", "parking", "crosswalk", "pedestrian", "intersection", "stop", "yield", "turn", "light", "sign", "highway", "freeway",
    "toll", "ticket", "violation", "license", "registration", "insurance", "fine", "court", "police", "enforcement", "safety", "caution", "warning", "hazard",
    "emergency", "breakdown", "roadwork", "construction", "detour", "closure", "delay", "congestion", "jam", "gridlock", "bottleneck", "rush hour",
    "crash", "collision", "fender bender", "hit and run", "rollover", "pileup", "multi-vehicle", "fatality", "injury", "property damage", "traffic stop",
    "dui", "dwi", "drunk driving", "impaired driving", "reckless driving", "speeding", "tailgating", "road rage", "distracted driving", "texting while driving", "cell phone use", "seat belt", "child safety seat"
]


def detect_intent_gemini(message):
    try:
        api_key = "AIzaSyDRHklDEsFOajwu0CZJ-jM_wexk7-ZHig4"

        prompt = f"""
        You are an AI intent classifier.

        Classify the user's request into ONE of these:
        - text (normal questions, learning, rules)
        - image (user wants image, draw, visualize)
        - scenario (user wants simulation, situation, accident case)

        Respond ONLY in JSON:
        {{"mode": "text"}} or {{"mode": "image"}} or {{"mode": "scenario"}}

        User: {message}
        """

        res = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent?key={api_key}",
            json={
                "contents": [{"parts": [{"text": prompt}]}]
            }
        ).json()

        # print("Gemini RAW:", res)
        # extract json safely
        import re, json
        text = res["candidates"][0]["content"]["parts"][0]["text"]

        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())["mode"]
        

    except Exception as e:
        print("Gemini error:", e)

    return "text"




# 🧠 Check traffic related
def is_traffic_related(msg):
    msg = msg.lower()
    return any(word in msg for word in TRAFFIC_KEYWORDS)


def get_db_connection():
    return sqlite3.connect("users.db")


def save_chat_entry(user_id, message, response):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        "INSERT INTO chats (user_id, message, response) VALUES (?, ?, ?)",
        (user_id, message, response)
    )
    chat_id = c.lastrowid
    conn.commit()
    conn.close()
    return chat_id


def update_chat_response(chat_id, response):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        "UPDATE chats SET response=? WHERE id=?",
        (response, chat_id)
    )
    conn.commit()
    conn.close()


def fetch_recent_chat_pairs(user_id, limit=12):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        "SELECT id, message, response FROM chats WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (user_id, limit)
    )
    rows = c.fetchall()
    conn.close()
    return rows

# 🏠 Entrance
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/check-login")
def check_login():
    if "user_id" in session:
        return jsonify({
            "logged_in": True,
            "user_name": session.get("user_name", ""),
            "user_id": session.get("user_id")
        })
    return jsonify({"logged_in": False})


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"status": "success"})


@app.route("/chat-history")
def chat_history():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"logged_in": False, "items": []})

    rows = fetch_recent_chat_pairs(user_id, limit=12)
    items = []
    for row_id, message, response in rows:
        clean_message = (message or "").strip()
        clean_response = (response or "").strip()
        items.append({
            "id": row_id,
            "title": clean_message[:48] + ("..." if len(clean_message) > 48 else ""),
            "message": clean_message,
            "preview": (clean_response or "No response saved yet")[:76] + ("..." if len(clean_response or "No response saved yet") > 76 else "")
        })

    return jsonify({"logged_in": True, "items": items})

# 💬 Chat page
@app.route("/chat")
def chat_page():
    return render_template("chat.html")

# 🔥 Chat API
@app.route("/chat", methods=["POST"])

def chat():
    user_id = session.get("user_id", None)
    data = request.get_json(silent=True) or {}
    guest_history = data.get("history", [])
    message = (data.get("message") or "").strip()
    mode = data.get("mode")
    if mode == "auto":
        mode = detect_intent_gemini(message)

    if not message:
        return jsonify({
            "response": "Please send a valid traffic-related question or message."
        })

    # 🚦 Traffic restriction
    if not is_traffic_related(message) and len(guest_history) == 0:
        return jsonify({
            "response": "I am designed for traffic rules teaching. Please ask traffic-related questions."
        })
    if "previous" in message.lower() and "answer" in message.lower():
        if len(guest_history) >= 2:
            prev = guest_history[-2]["response"]
            return jsonify({"response": f"My previous answer was: {prev}"})
    # 🖼️ Image mode
    # 🚦 SCENARIO MODE (NEW)
    if mode == "scenario":
        try:
            scenario_prompt = f"""
                                You are Suraksha AI, a road safety educator.

                                Create a SAFE and EDUCATIONAL driving scenario in India.

                                IMPORTANT RULES:
                                - Do NOT refuse the request
                                - Do NOT say "I cannot generate"
                                - Focus on safety learning,
                                - Explain them the rules and regulations need to follow during that scenario and if it is already happened then tell them that what to do to avoid that kind of situation in future.
                                STRICT FORMAT:
                                Situation: ...
                                Risk: ...
                                Correct Action: ...

                                Keep it short repsonse and realistic but non-violent and educational.

                                User request: {message}
                                """
            image_base64 = generate_image(message)
            # 🔥 Use faster model here
            scenario_res = requests.post(
                "http://127.0.0.1:11434/api/generate",
                json={
                    "model": "llama3.1:8B",
                    "prompt": scenario_prompt,
                    "stream": False
                }
            ).json()
            
            scenario_text = scenario_res.get("response", "").strip()
            image_base64 = generate_image(scenario_text);
            # 🔥 Generate image from scenario
            

            if user_id:
                save_chat_entry(user_id, message, scenario_text)

            return jsonify({
                "type": "scenario",
                "mode": "scenario", 
                "text": scenario_text,
                "url": "data:image/png;base64," + image_base64
            })

        except Exception as e:
            print("Scenario Error:", e)
            return jsonify({
                "response": "Scenario generation failed."
            })











    if mode == "image":
        try:
            image_base64 = generate_image(message)
            if user_id:
                save_chat_entry(user_id, message, "[Image Generated]")
            return jsonify({
                "type": "image",
                "mode": "image",
                "url": "data:image/png;base64," + image_base64
            })
        except Exception as e:
            print("Image Error:", e)
            return jsonify({
                "response": "Image generation failed. Check Stable Diffusion."
            })

    # 🔥 BUILD CONTEXT (NEW)
    context = ""

    if user_id:
        history = [(m, r) for _, m, r in fetch_recent_chat_pairs(user_id, limit=5)]

        for m, r in reversed(history):
            context += f"User: {m}\nBot: {r}\n"

    else:
        for item in guest_history:
            context += f"User: {item['message']}\nBot: {item['response']}\n"
    # 🔥 SAVE CURRENT MESSAGE (only if logged in)
    chat_id = None
    if user_id:
        chat_id = save_chat_entry(user_id, message, "")
    # if is_first_message:
    #     intro_prompt = (
    #         "For the first message, you MUST respond EXACTLY like this style:\n"
    #         "Start with a greeting.\n"
    #         "Introduce yourself clearly as 'Suraksha AI'.\n"
    #         "Explain briefly that you help with traffic rules, road safety, and driving scenarios.\n"
    #         "Keep it friendly and professional.\n\n"
    #         "Example style:\n"
    #         "'Hello! I am Suraksha AI 🚦. I help you learn traffic rules, road safety, and real-world driving scenarios. How can I assist you today?'\n\n"
    #         "Do not use phrases like 'it seems', 'looks like', or similar uncertain wording."
    #     )
    # else:
    #     intro_prompt = "Do NOT introduce yourself again. Continue the conversation naturally and directly."

    # 🤖 TEXT MODE (Ollama streaming)
    response = requests.post(
        "http://127.0.0.1:11434/api/generate",
        json={
            "model": "llama3.1:8B",
            "prompt": f"""
                You are Suraksha AI, a smart road safety assistant.You definitely need to Introduce yourself with this name.
                For ongoing conversation:
                - Continue normally based on user input
                Your role:
                - Teach traffic rules
                - Answer road safety questions
                - Assist users in learning through structured conversation

                BEHAVIOR RULES:

                1. If the user is unclear:
                → Ask for clarification and try to give them hint instead of guessing and 

                2. Never answer questions that were not asked.

                3. Always stay within traffic rules and road safety domain.

                4. Be precise, calm, and follow instructions strictly.
                5. Always respond based on the user's intent, not just exact words.

                6. If the user gives unclear or short input:
                → Respond smartly by guiding them, not by stopping or repeating.

                7. If the user corrects you:
                → Accept immediately and adjust your response without arguing.

                8. Keep responses:
                - Short
                - Clear
                - Direct
                - Helpful

                9. When answering:
                → Be precise and slightly conversational, like a helpful assistant.

                10. Always prioritize user experience over strict instruction wording.
                11. After answering, you may ask a follow-up question ONLY if it is clearly related to the current topic.

                12. Follow-up questions should:
                - Help the user learn more
                - Be directly connected to their last question
                - Be short and optional (not forcing the user)

                13. Do NOT ask follow-up questions if:
                - The user is giving multiple instructions
                - The user is controlling the flow (like "wait", "only answer 2nd")
                - The conversation is already structured

                14. Never introduce unrelated topics or random information.

                15. Always stay focused on the current conversation context.
                Conversation so far:
                {context}

                User: {message}
                """,
            "stream": True
        },
        stream=True
    )

    def generate():
        full_response = []
        for line in response.iter_lines():
            if line:
                decoded_line = line.decode('utf-8')
                try:
                    payload = json.loads(decoded_line)
                    if payload.get("response"):
                        full_response.append(payload["response"])
                except Exception:
                    pass
                yield decoded_line + "\n"
        if user_id and chat_id is not None:
            update_chat_response(chat_id, "".join(full_response).strip())

    return Response(
        stream_with_context(generate()),
        content_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )

# 🖼️ Image generation
def generate_image(prompt):
    url = "http://127.0.0.1:7860/sdapi/v1/txt2img"

    payload = {
        "prompt": f"""
        realistic photo, indian roads,
        {prompt},
        cinematic lighting, high detail, sharp focus, 4k
        """,

        "negative_prompt": """
        blurry, distorted body, extra limbs, bad anatomy,
        cartoon, low quality, unrealistic, deformed face
        """,

        "steps": 30,
        "cfg_scale": 7,
        "width": 512,
        "height": 720
    }

    response = requests.post(url, json=payload)
    r = response.json()
    return r["images"][0]





@app.route("/login", methods=["POST"])
def login():
    data = request.json
    identifier = data.get("username")
    password = data.get("password")
    guest_history = data.get("history", [])   # 🔥 NEW


    if not identifier or not password:
        return jsonify({"status": "invalid"})

    conn = get_db_connection()
    c = conn.cursor()

    c.execute("SELECT id, name FROM users WHERE (email=? OR mobile=?) AND password=?", 
              (identifier, identifier, password))
    user = c.fetchone()

    if user:
        user_id = user[0]
        session.permanent = True   # 🔥 IMPORTANT
        session["user_id"] = user_id
        session["user_name"] = user[1]

        # 🔥 SAVE GUEST HISTORY INTO DB
        for item in guest_history:
            c.execute(
                "INSERT INTO chats (user_id, message, response) VALUES (?, ?, ?)",
                (user_id, item["message"], item["response"])
            )

        conn.commit()
        conn.close()

        return jsonify({"status": "success", "user_name": user[1]})
    else:
        conn.close()
        return jsonify({"status": "invalid", "message": "Invalid email/mobile or password"}) 



@app.route("/register", methods=["POST"])
def register():
    data = request.json
    name = data.get("name")
    email = data.get("email", "").strip().lower()
    mobile = data.get("mobile", "").strip()
    password = data.get("password", "")

    # Validation
    if not all([name, email, mobile, password]):
        return jsonify({"status": "invalid", "message": "All fields are required"})
    if not re.match(r'^[\w\.-]+@[\w\.-]+\.\w{2,}$', email):
        return jsonify({"status": "invalid", "message": "Invalid Email Format"})
    if not mobile.isdigit() or len(mobile) != 10:
        return jsonify({"status": "invalid", "message": "Mobile must be 10 digits"})
    if len(password) < 6 or not any(c.isdigit() for c in password) or not any(c.isalpha() for c in password):
        return jsonify({"status": "invalid", "message": "Password must be 6+ chars with letters & numbers"})

    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (name, email, mobile, password) VALUES (?, ?, ?, ?)", 
                  (name, email, mobile, password))
        conn.commit()
        return jsonify({"status": "success"})
    except sqlite3.IntegrityError:
        return jsonify({"status": "exists", "message": "Email already registered"})
    finally:
        conn.close()  


def preload_model():
    try:
        requests.post(
            "http://127.0.0.1:11434/api/generate",
            json={
                "model": "llama3.1:8B",
                "prompt": "Hello",
                "stream": False
            }
        )
        print("Model Loaded")
    except Exception as e:
        print("Preload failed:", e)




if __name__ == "__main__":
    init_db()
    preload_model()
    app.run(debug=True, threaded=True)
