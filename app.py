import os
import json
import requests
from datetime import datetime
from flask import Flask, request, redirect, url_for, session, jsonify, render_template
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

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev-secret-key')
app.config['SESSION_COOKIE_SECURE'] = False  # Set to True in production with HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
CORS(app)

MYSQL_HOST = os.getenv('MYSQL_HOST', 'localhost')
MYSQL_USER = os.getenv('MYSQL_USER', 'root')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', '')
MYSQL_DB = os.getenv('MYSQL_DB', 'grocery_db')

def get_db_connection():
    return mysql.connector.connect(
        host=MYSQL_HOST,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DB
    )

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
    def __init__(self, user_id):
        self.user_id = user_id
        self.messages = [
            {
                'role': 'assistant',
                'text': 'Hello! How can I help you with your grocery shopping today?',
                'timestamp': datetime.now().isoformat()
            }
        ]
        self.cart = []
        self.language = 'en'  
        self.current_language = 'en'
        
        try:
            self.chat = model.start_chat(history=[])
            print(f"Created new chat session for user {user_id}")
        except Exception as e:
            print(f"Error initializing chat model: {str(e)}")
            self.chat = None

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
            chat_sessions[userinfo['sub']] = ChatSession(userinfo['sub'])
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
    if user_id not in chat_sessions:
        chat_sessions[user_id] = ChatSession(user_id)
    
    chat_session = chat_sessions[user_id]
    
    try:
        user_message = {
            'role': 'user',
            'text': message,
            'timestamp': datetime.now().isoformat()
        }
        chat_session.messages.append(user_message)

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
        # Add to cart intent
        elif re.search(r"add to cart\s*:\s*pid=(\d+),\s*q=(\d+)", message, re.IGNORECASE):
            cart_match = re.search(r"add to cart\s*:\s*pid=(\d+),\s*q=(\d+)", message, re.IGNORECASE)
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
            try:
                response = chat_session.chat.send_message(message)
                response_text = response.text if hasattr(response, 'text') else "I didn't get a proper response."
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
    if user_id not in chat_sessions:
        return jsonify({'messages': []})
    
    return jsonify({'messages': chat_sessions[user_id].messages})

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

if __name__ == '__main__':
    app.run(debug=True)