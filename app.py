from flask import Flask, request, jsonify, send_from_directory, redirect, session
from flask_cors import CORS
import psycopg2
import os
import random
import requests
import urllib.parse
from datetime import datetime

app = Flask(__name__, static_folder='.')
app.secret_key = os.environ.get('SECRET_KEY', 'default-secret-key-123')
CORS(app)

# Настройки из переменных окружения Railway
ADMIN_PASS = "34125"
DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1485332673080590429/0ZD2pBkATVamUPhpdriBzBUzvMP5oOKo4H91JO4maCaRGIty1ipE7ZYnrGjL2dSa7-0d"
DATABASE_URL = os.environ.get('DATABASE_URL', '')
UB_TOKEN = os.environ.get('UB_TOKEN', '')
GUILD_ID = '1425098428509061202'
DISCORD_CLIENT_ID = os.environ.get('DISCORD_CLIENT_ID', '')
DISCORD_CLIENT_SECRET = os.environ.get('DISCORD_CLIENT_SECRET', '')
SITE_URL = os.environ.get('SITE_URL', 'https://caserequiem-production.up.railway.app').rstrip('/')

if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

def get_conn():
    if not DATABASE_URL:
        raise Exception('DATABASE_URL не задан!')
    return psycopg2.connect(DATABASE_URL)

def send_discord(title, description, color=0x5865F2):
    try:
        data = {"embeds": [{"title": title, "description": description, "color": color,
                            "timestamp": datetime.utcnow().isoformat() + "Z"}]}
        requests.post(DISCORD_WEBHOOK, json=data, timeout=5)
    except Exception as e:
        print(f"Discord error: {e}")

# ============ Инициализация БД ============

def init_db():
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            discord_id TEXT PRIMARY KEY,
            username TEXT,
            balance INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS keys (
            key TEXT PRIMARY KEY,
            type TEXT,
            amount INTEGER,
            is_used BOOLEAN DEFAULT FALSE
        )''')
        conn.commit()
        c.close()
        conn.close()
        print("✅ База данных инициализирована")
    except Exception as e:
        print(f"❌ Ошибка БД: {e}")

# ============ API Эндпоинты ============

@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')

@app.route('/api/get_balance')
def get_balance():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT balance, username FROM users WHERE discord_id = %s", (user_id,))
        res = c.fetchone()
        c.close()
        conn.close()
        if res:
            return jsonify({"balance": res[0], "username": res[1]})
        return jsonify({"balance": 0})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/open_case', methods=['POST'])
def open_case():
    # Простейшая логика рандома для примера
    items = ["Common", "Rare", "Epic", "Legendary"]
    weights = [70, 20, 9, 1]
    res = random.choices(items, weights=weights)[0]
    return jsonify({"success": True, "item": res})

# ============ Discord Auth ============

@app.route('/api/auth/discord')
def discord_login():
    params = {
        'client_id': DISCORD_CLIENT_ID,
        'redirect_uri': f"{SITE_URL}/api/auth/callback",
        'response_type': 'code',
        'scope': 'identify'
    }
    return redirect(f"https://discord.com/api/oauth2/authorize?{urllib.parse.urlencode(params)}")

@app.route('/api/auth/callback')
def discord_callback():
    code = request.args.get('code')
    if not code: return redirect('/?error=no_code')

    token_data = {
        'client_id': DISCORD_CLIENT_ID,
        'client_secret': DISCORD_CLIENT_SECRET,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': f"{SITE_URL}/api/auth/callback"
    }
    
    r = requests.post('https://discord.com/api/oauth2/token', data=token_data)
    if r.status_code != 200: return redirect('/?error=token_err')
    
    token = r.json().get('access_token')
    u_info = requests.get('https://discord.com/api/users/@me', headers={'Authorization': f'Bearer {token}'}).json()
    
    d_id, d_name = u_info['id'], u_info['username']
    session['user_id'] = d_id
    
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO users (discord_id, username) VALUES (%s, %s) ON CONFLICT (discord_id) DO UPDATE SET username = %s", (d_id, d_name, d_name))
    conn.commit()
    c.close()
    conn.close()
    
    return redirect('/')

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
