import os
import json
import requests
from datetime import datetime
from flask import Flask, request, redirect, url_for, session, jsonify, render_template, send_from_directory
from flask_cors import CORS
import google.generativeai as genai
from dotenv import load_dotenv
import mysql.connector
import re
try:
    from googletrans import Translator
    translator = Translator()
except ImportError:
    translator = None
import pandas as pd
from werkzeug.utils import secure_filename

load_dotenv()

app = Flask(__name__, static_folder='static')
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev-secret-key')
app.config['SESSION_COOKIE_SECURE'] = False  # Set to True in production with HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Serve static files
@app.route('/static/<path:path>')
def serve_static(path):
    return send_from_directory('static', path)
CORS(app)

MYSQL_HOST = os.getenv('MYSQL_HOST', 'bpo977qofmifrmo5ciff-mysql.services.clever-cloud.com')
MYSQL_USER = os.getenv('MYSQL_USER', 'uikso7x7mfnszsh0')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', 'tp2Zws86wsTBZrzVyGrU')
MYSQL_DB = os.getenv('MYSQL_DB', 'bpo977qofmifrmo5ciff')

def get_db_connection():
    """Create and return a database connection with error handling"""
    try:
        conn = mysql.connector.connect(
            host="bpo977qofmifrmo5ciff-mysql.services.clever-cloud.com",
            user="uikso7x7mfnszsh0",
            password="tp2Zws86wsTBZrzVyGrU",
            database="bpo977qofmifrmo5ciff",
            port=3306,
            ssl_disabled=True,  # Disable SSL as in a.py
            connect_timeout=10
        )
        if conn.is_connected():
            print("Successfully connected to the database")
            return conn
        else:
            print("Connection failed")
            return None
    except mysql.connector.Error as err:
        print(f"❌ MySQL Connection Error: {err}")
        return None


def get_product_answer_from_db(message: str) -> str | None:
    message_lower = message.lower()
    patterns = [
        r"price of ([^?.!,\n]+)",
        r"cost of ([^?.!,\n]+)",
        r"details of ([^?.!,\n]+)",
        r"information about ([^?.!,\n]+)",
        r"tell me about ([^?.!,\n]+)",
        r"do you have ([^?.!,\n]+)",
    ]
    search_term = None
    for pattern in patterns:
        match = re.search(pattern, message_lower, re.IGNORECASE)
        if match:
            search_term = match.group(1).strip()
            break
    if not search_term:
        return None
    try:
        conn = get_db_connection()
        if not conn:
            return None
        cursor = conn.cursor()
        like_pattern = f"%{search_term}%"
        cursor.execute(
            """
            SELECT id, name, description, category, price, stock
            FROM product_catalog
            WHERE is_active = 1
              AND (LOWER(name) LIKE %s OR LOWER(category) LIKE %s)
            """,
            (like_pattern, like_pattern),
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        if not rows:
            return None
        response_lines = ["Here is what I found in our product catalog:"]
        for row in rows:
            pid, name, description, category, price, stock = row
            response_lines.append(
                f"- ID: {pid}, {name} ({category}): {description} | Price: ${price:.2f} | Stock: {stock}"
            )
        return "\n".join(response_lines)
    except Exception as e:
        print(f"Error in get_product_answer_from_db: {e}")
        return None


def is_product_question(message: str) -> bool:
    message_lower = message.lower()
    patterns = [
        r"price of ([^?.!,\n]+)",
        r"cost of ([^?.!,\n]+)",
        r"details of ([^?.!,\n]+)",
        r"information about ([^?.!,\n]+)",
        r"tell me about ([^?.!,\n]+)",
        r"do you have ([^?.!,\n]+)",
    ]
    for pattern in patterns:
        if re.search(pattern, message_lower, re.IGNORECASE):
            return True
    return False


GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')
GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"

ADMIN_EMAILS = set(os.getenv('ADMIN_EMAILS', '').split(',')) if os.getenv('ADMIN_EMAILS') else {"admin@example.com"}

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
genai.configure(api_key=GEMINI_API_KEY)

try:
    model = genai.GenerativeModel('gemini-2.5-flash')
    print("Gemini 2.5 Flash model initialized successfully")
    
    # Set up the chat with system instruction
    chat = model.start_chat(history=[])
    chat.send_message("""
    You are a helpful grocery shopping assistant. Help users find products, 
    manage their shopping cart, and answer grocery-related questions. 
    Be friendly, concise, and helpful. Keep responses brief and to the point.
    """)
    
except Exception as e:
    print(f"Error initializing Gemini model: {str(e)}")
    print("Falling back to a simple response system")
    
    class SimpleModel:
        def __init__(self):
            self.history = []
        
        def start_chat(self, history=None):
            self.history = history or []
            return self
        
        def send_message(self, message):
            responses = [
                "I'm your grocery assistant. How can I help you today?",
                "I can help you find products and manage your shopping list.",
                "Would you like me to add anything to your cart?",
                "I found some great deals on fresh produce today!",
                "Your cart currently has 3 items."
            ]
            import random
            response = random.choice(responses)
            return type('obj', (object,), {'text': response})
    
    model = SimpleModel()
    print("Using simple response system")

# In-memory storage for chat sessions
# Structure: { user_id: { 'active_session_id': str, 'sessions': {session_id: ChatSession} } }
chat_sessions = {}

# Supported languages
SUPPORTED_LANGUAGES = [
    {'code': 'en', 'name': 'English'},
    {'code': 'es', 'name': 'Español'},
    {'code': 'fr', 'name': 'Français'},
    {'code': 'de', 'name': 'Deutsch'},
    {'code': 'ur', 'name': 'اردو'},
    {'code': 'ar', 'name': 'العربية'},
]

# System instruction for the chatbot
SYSTEM_INSTRUCTION = """You are 'Personal Grocery Chatbot', a friendly and helpful AI assistant.
Your goal is to assist users with their grocery shopping needs. This includes:
- Creating and managing grocery lists (e.g., "add milk to my list", "what's on my list?", "remove eggs").
- Suggesting items based on user preferences or meal plans.
- Finding recipes based on ingredients.
- Providing information about products (like nutritional facts, storage tips, or alternatives).
- Answering general questions related to groceries and cooking.
- Helping users add products to their cart and place orders.

**To add a product to your cart, instruct the user to type:**
add to cart: product_id=<id>, quantity=<qty>

**To place an order, instruct the user to type:**
place order

Interaction Guidelines:
- Be polite, empathetic, and maintain a friendly conversational tone.
- Keep responses concise and to the point, but provide enough detail to be helpful.
- If a user asks for something outside of grocery topics, gently guide them back to grocery-related topics.
- Use markdown for formatting lists or important information when appropriate.
- Do not ask for personal identifiable information (PII)."""

# Supported languages
SUPPORTED_LANGUAGES = [
    {'code': 'en', 'name': 'English'},
    {'code': 'es', 'name': 'Español'},
    {'code': 'fr', 'name': 'Français'},
    {'code': 'de', 'name': 'Deutsch'},
    {'code': 'ur', 'name': 'اردو'},
    {'code': 'ar', 'name': 'العربية'},
]

class ChatSession:
    def __init__(self, user_id, session_id=None, title=None):
        self.user_id = user_id
        self.session_id = session_id or str(datetime.now().timestamp()).replace('.', '')
        self.title = title or "New chat"
        now_iso = datetime.now().isoformat()
        self.created_at = now_iso
        self.updated_at = now_iso
        self.messages = [
            {
                'id': '1',
                'role': 'assistant',
                'text': 'Hello! How can I help you with your grocery shopping today?',
                'timestamp': now_iso
            }
        ]
        self.cart = []
        self.language = 'en'  
        self.current_language = 'en'
        
        try:
            self.chat = model.start_chat(history=[])
            print(f"Created new chat session for user {user_id} with session_id={self.session_id}")
        except Exception as e:
            print(f"Error initializing chat model: {str(e)}")
            self.chat = None

        if hasattr(self, 'chat') and self.chat is not None:
            self.chat.send_message(
                "You are a helpful grocery shopping assistant. "
                "Help users find products, manage their shopping cart, "
                "and answer questions about groceries. Be friendly and concise. "
                "When showing product prices, format them in a clear way. "
                "When adding items to cart, confirm the action and update the cart total."
            )

    def add_message(self, role, text):
        message = {
            'id': str(len(self.messages) + 1),
            'role': role,
            'text': text,
            'timestamp': datetime.now().isoformat()
        }
        self.messages.append(message)
        self.updated_at = message['timestamp']
        return message

    async def get_ai_response(self, user_input):
        try:
            self.add_message('user', user_input)
            
            response = await self.chat.send_message_async(user_input)
            
            bot_message = self.add_message('model', response.text)
            
            return bot_message
        except Exception as e:
            print(f"Error getting AI response: {str(e)}")
            error_message = f"Sorry, I encountered an error: {str(e)[:100]}"
            return self.add_message('model', error_message)

def load_chat_sessions_from_db(user_id):
    try:
        conn = get_db_connection()
        if not conn:
            return []
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT session_id, title, created_at, updated_at
            FROM chat_sessions
            WHERE user_id = %s
            ORDER BY updated_at DESC
            """,
            (user_id,),
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return rows
    except Exception as e:
        print(f"Error loading chat sessions from DB: {e}")
        return []


def save_chat_session_to_db(session: ChatSession):
    try:
        conn = get_db_connection()
        if not conn:
            return
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO chat_sessions (session_id, user_id, title, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                title = VALUES(title),
                updated_at = VALUES(updated_at)
            """,
            (
                session.session_id,
                session.user_id,
                session.title,
                session.created_at,
                session.updated_at,
            ),
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error saving chat session to DB: {e}")


def get_or_create_user_sessions(user_id):
    if user_id not in chat_sessions:
        user_data = {
            'active_session_id': None,
            'sessions': {},
        }
        rows = load_chat_sessions_from_db(user_id)
        if rows:
            for row in rows:
                session_id, title, created_at, updated_at = row
                s = ChatSession(user_id, session_id=session_id, title=title)
                # Preserve original timestamps for display/order
                try:
                    s.created_at = created_at.isoformat()
                except AttributeError:
                    s.created_at = str(created_at)
                try:
                    s.updated_at = updated_at.isoformat()
                except AttributeError:
                    s.updated_at = str(updated_at)
                user_data['sessions'][s.session_id] = s
            user_data['active_session_id'] = rows[0][0]
        else:
            first_session = ChatSession(user_id)
            save_chat_session_to_db(first_session)
            user_data['active_session_id'] = first_session.session_id
            user_data['sessions'][first_session.session_id] = first_session
        chat_sessions[user_id] = user_data
    return chat_sessions[user_id]

def get_active_chat_session(user_id):
    user_data = get_or_create_user_sessions(user_id)
    active_id = user_data.get('active_session_id')
    session = user_data['sessions'].get(active_id)
    if not session:
        session = ChatSession(user_id)
        user_data['sessions'][session.session_id] = session
        user_data['active_session_id'] = session.session_id
    return session

def create_new_chat_session(user_id, title=None):
    user_data = chat_sessions.get(user_id)
    new_session = ChatSession(user_id, title=title or "New chat")
    if not user_data:
        chat_sessions[user_id] = {
            'active_session_id': new_session.session_id,
            'sessions': {new_session.session_id: new_session}
        }
    else:
        user_data['sessions'][new_session.session_id] = new_session
        user_data['active_session_id'] = new_session.session_id
    save_chat_session_to_db(new_session)
    return new_session

@app.route('/')
def index():
    if 'user' not in session:
        return redirect(url_for('login'))
   
    view_mode = session.get('view_mode', 'admin' if session.get('is_admin') else 'user')
    if session.get('is_admin') and view_mode == 'admin':
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SHOW COLUMNS FROM product_catalog")
        columns = cursor.fetchall()
        cursor.close()
        conn.close()
        return render_template('admin_dashboard.html', admin=session['user'], columns=columns, view_mode='admin')

    return render_template('index.html', 
                         user=session['user'], 
                         supported_languages=SUPPORTED_LANGUAGES,
                         current_language=session.get('current_language', 'en'),
                         api_key_configured=bool(os.getenv('GEMINI_API_KEY')),
                         view_mode='user')

@app.route('/toggle_view')
def toggle_view():
    if not session.get('is_admin'):
        return redirect(url_for('index'))
    session['view_mode'] = 'user' if session.get('view_mode', 'admin') == 'admin' else 'admin'
    return redirect(url_for('index'))

@app.route('/login')
def login():
    if 'user' in session:
        return redirect(url_for('index'))
    return render_template('login.html', google_client_id=GOOGLE_CLIENT_ID)

@app.route('/auth/google')
def google_auth():
    google_provider_cfg = requests.get(GOOGLE_DISCOVERY_URL).json()
    
    auth_url = (
        f"{google_provider_cfg['authorization_endpoint']}?"
        f"client_id={GOOGLE_CLIENT_ID}&"
        "response_type=code&"
        "scope=openid%20email%20profile&"
        f"redirect_uri=http://localhost:5000/auth/google/callback&"
        "access_type=offline"
    )
    return redirect(auth_url)

@app.route('/auth/google/callback')
def google_auth_callback():
    code = request.args.get('code')
    if not code:
        return "Error: No code provided", 400
    try:
        google_provider_cfg = requests.get(GOOGLE_DISCOVERY_URL).json()
        token_endpoint = google_provider_cfg["token_endpoint"]
        token_data = {
            'code': code,
            'client_id': GOOGLE_CLIENT_ID,
            'client_secret': GOOGLE_CLIENT_SECRET,
            'redirect_uri': 'http://localhost:5000/auth/google/callback',
            'grant_type': 'authorization_code',
        }
        token_response = requests.post(
            token_endpoint,
            data=token_data,
            headers={'Content-Type': 'application/x-www-form-urlencoded'}
        )
        if token_response.status_code != 200:
            return f"Error getting tokens: {token_response.text}", 400
        tokens = token_response.json()
        userinfo_endpoint = google_provider_cfg["userinfo_endpoint"]
        userinfo_response = requests.get(
            userinfo_endpoint,
            headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )
        if userinfo_response.status_code != 200:
            return f"Error getting user info: {userinfo_response.text}", 400
        userinfo = userinfo_response.json()
        
        session['user'] = {
            'id': userinfo['sub'],
            'name': userinfo.get('name', 'User'),
            'email': userinfo.get('email', ''),
            'picture': userinfo.get('picture', '')
        }
        
        session['is_admin'] = userinfo.get('email') in ADMIN_EMAILS
    
        if userinfo['sub'] not in chat_sessions:
            get_or_create_user_sessions(userinfo['sub'])
        return redirect(url_for('index'))
    except Exception as e:
        return f"Error during authentication: {str(e)}", 500

@app.route('/logout')
def logout():
    session.pop('user', None)
    session.pop('is_admin', None)
    return redirect(url_for('login'))

@app.route('/api/chat', methods=['POST'])
def chat():
    if 'user' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    data = request.json
    message = data.get('message')
    
    if not message:
        return jsonify({'error': 'No message provided'}), 400
    
    user_id = session['user']['id']
    session_id = data.get('session_id')
    user_data = get_or_create_user_sessions(user_id)

    if session_id and session_id in user_data['sessions']:
        user_data['active_session_id'] = session_id
        chat_session = user_data['sessions'][session_id]
    else:
        chat_session = get_active_chat_session(user_id)
    
    try:
        user_message = {
            'role': 'user',
            'text': message,
            'timestamp': datetime.now().isoformat()
        }
        chat_session.messages.append(user_message)

        # Auto-name new chats based on the first user query
        if not chat_session.title or chat_session.title == "New chat":
            raw_title = message.strip().replace('\n', ' ')
            if raw_title:
                if len(raw_title) > 40:
                    raw_title = raw_title[:40].rstrip() + "..."
                chat_session.title = raw_title
                try:
                    save_chat_session_to_db(chat_session)
                except Exception as e:
                    print(f"Error saving updated chat title: {e}")

        current_language = session.get('current_language', 'en')

        add_product_pattern = r"add product\s*:\s*name=(.*?),\s*description=(.*?),\s*category=(.*?),\s*price=([\d.]+),\s*stock=(\d+),\s*is_active=(\d)"
        match = re.search(add_product_pattern, message, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            description = match.group(2).strip()
            category = match.group(3).strip()
            price = float(match.group(4).strip())
            stock = int(match.group(5).strip())
            is_active = int(match.group(6).strip())
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO product_catalog (name, description, category, price, stock, is_active)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (name, description, category, price, stock, is_active)
                )
                conn.commit()
                cursor.close()
                conn.close()
                response_text = f"Product '{name}' added successfully to the catalog."
            except Exception as db_err:
                response_text = f"Failed to add product: {db_err}"
       
        elif re.search(r"\b(product show|show products|list products|display products)\b", message, re.IGNORECASE):
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT id, name, description, category, price, stock FROM product_catalog WHERE is_active=1 AND stock > 0")
                products = cursor.fetchall()
                cursor.close()
                conn.close()
                if products:
                    response_text = "Available products:\n"
                    for p in products:
                        response_text += f"- ID: {p[0]}, {p[1]} ({p[3]}): {p[2]} | Price: ${p[4]:.2f} | Stock: {p[5]}\n"
                else:
                    response_text = "No products available."
            except Exception as db_err:
                response_text = f"Failed to fetch products: {db_err}"

        elif re.search(r"\b(cart show|show cart|view cart)\b", message, re.IGNORECASE):
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT c.product_id, c.quantity, p.name, p.price
                    FROM cart c
                    LEFT JOIN product_catalog p ON c.product_id = p.id
                    WHERE c.user_id = %s
                    """,
                    (user_id,),
                )
                rows = cursor.fetchall()
                cursor.close()
                conn.close()
                if not rows:
                    response_text = "Your cart is currently empty."
                else:
                    response_lines = ["Your cart items:"]
                    for pid, qty, name, price in rows:
                        label = name or f"Product {pid}"
                        line = f"- {label} (ID: {pid}) x {qty}"
                        if price is not None:
                            line += f" | Price each: ${price:.2f}"
                        response_lines.append(line)
                    response_text = "\n".join(response_lines)
            except Exception as db_err:
                response_text = f"Failed to fetch cart items: {db_err}"

        # Add to cart intent
        elif re.search(r"add to cart\s*:\s*(?:pid|product_id)=(\d+),\s*(?:q|quantity)=(\d+)", message, re.IGNORECASE):
            cart_match = re.search(r"add to cart\s*:\s*(?:pid|product_id)=(\d+),\s*(?:q|quantity)=(\d+)", message, re.IGNORECASE)
            product_id = int(cart_match.group(1))
            quantity = int(cart_match.group(2))
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO cart (user_id, product_id, quantity) VALUES (%s, %s, %s)",
                    (user_id, product_id, quantity)
                )
                conn.commit()
                cursor.close()
                conn.close()
                response_text = f"Added product {product_id} (qty: {quantity}) to your cart."
            except Exception as db_err:
                response_text = f"Failed to add to cart: {db_err}"

        elif re.search(r"remove from cart\s*:\s*pid=(\d+)", message, re.IGNORECASE):
            remove_match = re.search(r"remove from cart\s*:\s*pid=(\d+)", message, re.IGNORECASE)
            product_id = int(remove_match.group(1))
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM cart WHERE user_id=%s AND product_id=%s LIMIT 1",
                    (user_id, product_id)
                )
                if cursor.rowcount == 0:
                    response_text = f"Product {product_id} was not found in your cart."
                else:
                    conn.commit()
                    response_text = f"Removed product {product_id} from your cart."
                cursor.close()
                conn.close()
            except Exception as db_err:
                response_text = f"Failed to remove from cart: {db_err}"
        
        elif re.search(r"place order", message, re.IGNORECASE):
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT product_id, quantity FROM cart WHERE user_id=%s", (user_id,))
                cart_items = cursor.fetchall()
                if not cart_items:
                    response_text = "Your cart is empty. Add products before placing an order."
                else:
                    
                    for item in cart_items:
                        cursor.execute(
                            "UPDATE product_catalog SET stock = stock - %s WHERE id = %s AND stock >= %s",
                            (item[1], item[0], item[1])
                        )
                        if cursor.rowcount == 0:
                            raise Exception(f"Insufficient stock for product_id={item[0]}")
                  
                    order_details = ", ".join([f"product_id={item[0]}, quantity={item[1]}" for item in cart_items])
                   
                    cursor.execute(
                        "INSERT INTO orders (user_id, order_details) VALUES (%s, %s)",
                        (user_id, order_details)
                    )
                    
                    cursor.execute("DELETE FROM cart WHERE user_id=%s", (user_id,))
                    conn.commit()
                    response_text = "Order placed successfully! Your cart is now empty."
                cursor.close()
                conn.close()
            except Exception as db_err:
                response_text = f"Failed to place order: {db_err}"
        else:
            response_text = ""
            product_answer = None
            try:
                product_answer = get_product_answer_from_db(message)
            except Exception as db_lookup_err:
                print(f"Error during product DB lookup: {db_lookup_err}")
            if product_answer:
                try:
                    if chat_session.chat is not None:
                        prompt = (
                            "The user asked: '" + message + "'. "
                            "Based on the following product data from our internal database, "
                            "answer the user's question in a short, natural way, then keep the data below for reference.\n\n"
                            + product_answer
                        )
                        response = chat_session.chat.send_message(prompt)
                        nlp_text = response.text if hasattr(response, 'text') else ""
                        response_text = (nlp_text + "\n\n" + product_answer).strip()
                    else:
                        response_text = product_answer
                except Exception as e:
                    print(f"Error getting NLP answer from model: {e}")
                    response_text = product_answer
            else:
                try:
                    response = chat_session.chat.send_message(message)
                    response_text = response.text if hasattr(response, 'text') else "I didn't get a proper response."
                    if is_product_question(message):
                        response_text += "\n\nNote: I couldn't find this product in our store database, so this answer is general information and may not match our current catalog."
                except Exception as e:
                    response_text = "I'm having trouble connecting to the AI service right now. Please try again later."

        if current_language != 'en' and translator:
            try:
                translated = translator.translate(response_text, dest=current_language)
                response_text = translated.text
            except Exception as trans_err:
                response_text += f"\n(Translation error: {trans_err})"

        bot_message = {
            'role': 'assistant',
            'text': response_text,
            'timestamp': datetime.now().isoformat()
        }
        chat_session.messages.append(bot_message)
        try:
            save_chat_session_to_db(chat_session)
        except Exception as e:
            print(f"Error persisting chat session metadata: {e}")
        print(f"Added bot response to history. Total messages: {len(chat_session.messages)}")

        if len(chat_session.messages) > 20:
            chat_session.messages = chat_session.messages[-20:]

        response_data = {
            'message': {
                'role': 'assistant',
                'text': response_text,
                'timestamp': datetime.now().isoformat()
            },
            'history': chat_session.messages,
            'cart': chat_session.cart,
            'status': 'success'
        }
        return jsonify(response_data)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/chat/history', methods=['GET'])
def get_chat_history():
    if 'user' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    user_id = session['user']['id']
    session_id = request.args.get('session_id')
    user_data = chat_sessions.get(user_id)
    if not user_data:
        session_obj = get_active_chat_session(user_id)
        return jsonify({'messages': session_obj.messages})

    if session_id and session_id in user_data['sessions']:
        session_obj = user_data['sessions'][session_id]
    else:
        session_obj = get_active_chat_session(user_id)

    return jsonify({'messages': session_obj.messages})


@app.route('/api/chat/sessions', methods=['GET'])
def list_chat_sessions():
    if 'user' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    user_id = session['user']['id']
    user_data = get_or_create_user_sessions(user_id)
    sessions_payload = []
    for sid, s in user_data['sessions'].items():
        sessions_payload.append({
            'id': sid,
            'title': s.title,
            'created_at': s.created_at,
            'updated_at': s.updated_at,
        })
    return jsonify({
        'sessions': sessions_payload,
        'active_session_id': user_data['active_session_id'],
    })


@app.route('/api/chat/sessions', methods=['POST'])
def create_chat_session():
    if 'user' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    user_id = session['user']['id']
    data = request.get_json(silent=True) or {}
    title = data.get('title') or "New chat"
    new_session = create_new_chat_session(user_id, title=title)
    user_data = chat_sessions[user_id]
    sessions_payload = []
    for sid, s in user_data['sessions'].items():
        sessions_payload.append({
            'id': sid,
            'title': s.title,
            'created_at': s.created_at,
            'updated_at': s.updated_at,
        })
    return jsonify({
        'id': new_session.session_id,
        'title': new_session.title,
        'sessions': sessions_payload,
        'active_session_id': user_data['active_session_id'],
    })


@app.route('/api/chat/sessions/<session_id>', methods=['DELETE'])
def delete_chat_session(session_id):
    if 'user' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    user_id = session['user']['id']
    user_data = get_or_create_user_sessions(user_id)

    if session_id not in user_data['sessions']:
        return jsonify({'error': 'Session not found'}), 404

    # Remove from DB
    try:
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM chat_sessions WHERE user_id = %s AND session_id = %s",
                (user_id, session_id),
            )
            conn.commit()
            cursor.close()
            conn.close()
    except Exception as e:
        print(f"Error deleting chat session from DB: {e}")

    # Remove from in-memory cache
    user_data['sessions'].pop(session_id, None)

    # Choose a new active session if needed
    if user_data['active_session_id'] == session_id:
        remaining_ids = list(user_data['sessions'].keys())
        if remaining_ids:
            user_data['active_session_id'] = remaining_ids[0]
        else:
            new_session = create_new_chat_session(user_id)
            user_data = chat_sessions[user_id]

    # Build payload
    sessions_payload = []
    for sid, s in user_data['sessions'].items():
        sessions_payload.append({
            'id': sid,
            'title': s.title,
            'created_at': s.created_at,
            'updated_at': s.updated_at,
        })

    return jsonify({
        'sessions': sessions_payload,
        'active_session_id': user_data['active_session_id'],
    })

@app.route('/api/language', methods=['POST'])
def set_language():
    if 'user' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    data = request.get_json()
    language = data.get('language')
    
    if not language or not any(lang['code'] == language for lang in SUPPORTED_LANGUAGES):
        return jsonify({'error': 'Invalid language'}), 400
    
    session['current_language'] = language
    return jsonify({'success': True})

@app.route('/admin/upload_excel', methods=['POST'])
def admin_upload_excel():
    if not session.get('is_admin'):
        return jsonify({'error': 'Not authorized'}), 403
    if 'excel-file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    file = request.files['excel-file']
    filename = secure_filename(file.filename)
    if not filename.endswith('.add to cart: product_id=2, quantity=3'):
        return jsonify({'error': 'Only .xlsx files are supported'}), 400
    try:
        df = pd.read_excel(file)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SHOW COLUMNS FROM product_catalog")
        db_columns = [col[0] for col in cursor.fetchall()]
        df = df[[col for col in df.columns if col in db_columns]]
        cursor.execute("DELETE FROM product_catalog")
        for _, row in df.iterrows():
            placeholders = ','.join(['%s'] * len(row))
            sql = f"INSERT INTO product_catalog ({','.join(row.index)}) VALUES ({placeholders})"
            cursor.execute(sql, tuple(row))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'success': True, 'message': 'Products replaced successfully.'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/orders', methods=['GET'])
def admin_get_orders():
    if not session.get('is_admin'):
        return jsonify({'error': 'Not authorized'}), 403
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, user_id, order_details, placed_at FROM orders ORDER BY placed_at DESC")
        orders = [
            {
                'id': row[0],
                'user_id': row[1],
                'order_details': row[2],
                'placed_at': row[3].strftime('%Y-%m-%d %H:%M:%S') if row[3] else ''
            }
            for row in cursor.fetchall()
        ]
        cursor.close()
        conn.close()
        return jsonify({'orders': orders})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# This is required for Vercel
app = app

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))