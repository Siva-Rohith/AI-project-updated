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
    c.execute("""
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
        )
    """)

    # Chats table
    

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
        api_key = "AIzaSyDRHk"

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

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, title, created_at
        FROM chat_sessions
        WHERE user_id = ?
        ORDER BY created_at DESC
    """, (user_id,)).fetchall()
    conn.close()

    return jsonify({
        "logged_in": True,
        "items": [dict(row) for row in rows]
    })



# 💬 Chat page
@app.route("/chat")
def chat_page():
    return render_template("chat.html")

@app.route("/new-chat", methods=["POST"])
def new_chat():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO chat_sessions (user_id, title)
        VALUES (?, ?)
    """, (session["user_id"], "New Chat"))

    session_id = cur.lastrowid
    conn.commit()
    conn.close()

    return jsonify({"session_id": session_id, "title": "New Chat"})




@app.route("/chat-session/<int:session_id>", methods=["GET"])
def get_chat_session(session_id):
    if "user_id" not in session:
        return jsonify([])

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    messages = conn.execute("""
        SELECT role, content
        FROM chat_messages
        WHERE session_id = ?
        ORDER BY created_at ASC
    """, (session_id,)).fetchall()
    conn.close()

    return jsonify([dict(msg) for msg in messages])






@app.route("/delete-chat/<int:session_id>", methods=["DELETE"])
def delete_chat(session_id):
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # verify session belongs to logged-in user
    existing = cur.execute("""
        SELECT id FROM chat_sessions
        WHERE id = ? AND user_id = ?
    """, (session_id, session["user_id"])).fetchone()

    if not existing:
        conn.close()
        return jsonify({"error": "Not found"}), 404

    # delete child messages first
    cur.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
    # delete parent session
    cur.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))

    conn.commit()
    conn.close()

    return jsonify({"status": "success", "deleted_id": session_id})





# 🔥 Chat API
@app.route("/chat", methods=["POST"])
def chat():
    user_id = session.get("user_id", None)
    data = request.get_json(silent=True) or {}
    guest_history = data.get("history", [])
    message = (data.get("message") or "").strip()
    session_id = data.get("session_id")
    mode = data.get("mode")

    if mode == "auto":
        mode = detect_intent_gemini(message)

    if user_id and not session_id:
        conn = get_db_connection()
        cur = conn.cursor()

        title = message[:60] if message else "New Chat"

        cur.execute("""
            INSERT INTO chat_sessions (user_id, title)
            VALUES (?, ?)
        """, (user_id, title))

        session_id = cur.lastrowid
        conn.commit()
        conn.close()

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
            # image_base64 = generate_image(message)
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
            

            if user_id and session_id:
                conn = get_db_connection()
                cur = conn.cursor()

                cur.execute("""
                    INSERT INTO chat_messages (session_id, role, content)
                    VALUES (?, ?, ?)
                """, (session_id, "user", message))

                cur.execute("""
                        INSERT INTO chat_messages (session_id, role, content)
                        VALUES (?, ?, ?)
                    """, (session_id, "bot", f"{scenario_text}||IMG||data:image/png;base64,{image_base64}"))

                conn.commit()
                conn.close()

            return jsonify({
                "type": "scenario",
                "mode": "scenario",
                "text": scenario_text,
                "url": "data:image/png;base64," + image_base64,
                "session_id": session_id
            })

        except Exception as e:
            print("Scenario Error:", e)
            return jsonify({
                "response": "Scenario generation failed."
            })











    if mode == "image":
        try:
            image_base64 = generate_image(message)
            if user_id and session_id:
                conn = get_db_connection()
                cur = conn.cursor()

                cur.execute("""
                    INSERT INTO chat_messages (session_id, role, content)
                    VALUES (?, ?, ?)
                """, (session_id, "user", message))

                cur.execute("""
                        INSERT INTO chat_messages (session_id, role, content)
                        VALUES (?, ?, ?)
                    """, (session_id, "bot", f"[IMAGE]||data:image/png;base64,{image_base64}"))

                conn.commit()
                conn.close()
            return jsonify({
                "type": "image",
                "mode": "image",
                "url": "data:image/png;base64," + image_base64,
                "session_id": session_id
            })
        except Exception as e:
            print("Image Error:", e)
            return jsonify({
                "response": "Image generation failed. Check Stable Diffusion."
            })

    # 🔥 BUILD CONTEXT (NEW)
    context = ""

    if user_id and session_id:
        conn = get_db_connection()
        conn.row_factory = sqlite3.Row

        history = conn.execute("""
            SELECT role, content
            FROM chat_messages
            WHERE session_id = ?
            ORDER BY created_at ASC
            LIMIT 10
        """, (session_id,)).fetchall()

        conn.close()

        temp_user = None
        for row in history:
            if row["role"] == "user":
                temp_user = row["content"]
            elif row["role"] == "bot" and temp_user:
                context += f"User: {temp_user}\nBot: {row['content']}\n"
                temp_user = None

    else:
        for item in guest_history:
            context += f"User: {item['message']}\nBot: {item['response']}\n"

    if user_id:
        conn = get_db_connection()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        if not session_id:
            cur.execute(
                "INSERT INTO chat_sessions (user_id, title) VALUES (?, ?)",
                (user_id, message[:40])
            )
            session_id = cur.lastrowid

        cur.execute("""
            INSERT INTO chat_messages (session_id, role, content)
            VALUES (?, ?, ?)
        """, (session_id, "user", message))

        conn.commit()

        
    # 🔥 SAVE CURRENT MESSAGE (only if logged in)
    # chat_id = None
    # if user_id:
    #     chat_id = save_chat_entry(user_id, message, "")
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
        if user_id and session_id:
            cur.execute("""
                INSERT INTO chat_messages (session_id, role, content)
                VALUES (?, ?, ?)
            """, (session_id, "bot", "".join(full_response).strip()))
            conn.commit()
            conn.close()
        yield json.dumps({"done": True, "session_id": session_id}) + "\n"
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
    # 1️⃣ Primary: Hugging Face FLUX
    try:
        HF_API_KEY = "HF-key"
        hf_res = requests.post(
            "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell",
            headers={"Authorization": f"Bearer {HF_API_KEY}"},
            json={"inputs": prompt},
            timeout=45
        )

        if hf_res.status_code == 200:
            return base64.b64encode(hf_res.content).decode("utf-8")
        else:
            print("HF failed:", hf_res.text)

    except Exception as e:
        print("HF Error:", e)

    # 2️⃣ Secondary: Replicate
    try:
        REPLICATE_API_TOKEN = "EG: r8_D6d6UyUT77cg"

        rep_res = requests.post(
            "https://api.replicate.com/v1/predictions",
            headers={
                "Authorization": f"Token {REPLICATE_API_TOKEN}",
                "Content-Type": "application/json"
            },
            json={
                "version": "black-forest-labs/flux-schnell",
                "input": {
                    "prompt": prompt
                }
            },
            timeout=45
        ).json()

        image_url = rep_res.get("output", [None])[0]
        if image_url:
            img = requests.get(image_url, timeout=30)
            return base64.b64encode(img.content).decode("utf-8")

    except Exception as e:
        print("Replicate Error:", e)

    # 3️⃣ Final fallback: Local Stable Diffusion
    try:
        url = "http://127.0.0.1:7860/sdapi/v1/txt2img"

        payload = {
            "prompt": f"{prompt}, highly detailed, high quality, realistic, sharp focus",
            "negative_prompt": "blurry, low quality, distorted, deformed, watermark, text",
            "steps": 35,
            "cfg_scale": 8,
            "width": 768,
            "height": 768,
            "sampler_name": "DPM++ 2M Karras"
        }

        response = requests.post(url, json=payload, timeout=60)
        r = response.json()
        return r["images"][0]

    except Exception as e:
        print("Local SD Error:", e)
        return None




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
        if guest_history:
            c.execute("INSERT INTO chat_sessions (user_id, title) VALUES (?, ?)", (user_id, "Guest Chat"))
            session_id = c.lastrowid

            for item in guest_history:
                c.execute(
                    "INSERT INTO chat_messages (session_id, role, content) VALUES (?, ?, ?)",
                    (session_id, "user", item["message"])
                )
                c.execute(
                    "INSERT INTO chat_messages (session_id, role, content) VALUES (?, ?, ?)",
                    (session_id, "bot", item["response"])
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
