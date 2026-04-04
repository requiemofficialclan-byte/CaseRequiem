from flask import Flask, request, jsonify, send_from_directory, redirect
from flask_cors import CORS
import psycopg2
from psycopg2 import errors
import os
import random
import string
import requests
import urllib.parse
from datetime import datetime

app = Flask(__name__, static_folder='.')
CORS(app)

ADMIN_PASS = "34125"
DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1485332673080590429/0ZD2pBkATVamUPhpdriBzBUzvMP5oOKo4H91JO4maCaRGIty1ipE7ZYnrGjL2dSa7-0d"
DATABASE_URL = os.environ.get('DATABASE_URL', '')
UB_TOKEN = os.environ.get('UB_TOKEN', '')
GUILD_ID = '1425098428509061202'
DISCORD_CLIENT_ID = os.environ.get('DISCORD_CLIENT_ID', '')
DISCORD_CLIENT_SECRET = os.environ.get('DISCORD_CLIENT_SECRET', '')
SITE_URL = os.environ.get('SITE_URL', 'https://caserequiem-production.up.railway.app')

if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

def get_conn():
    if not DATABASE_URL:
        raise Exception('DATABASE_URL не задан!')
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_conn()
    conn.autocommit = True  # Это критически важно для Railway!
    c = conn.cursor()
    
    # Создаем таблицу пользователей
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (username TEXT PRIMARY KEY, 
                  password TEXT, 
                  discord_id TEXT, 
                  balance INTEGER DEFAULT 0, 
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Пытаемся добавить колонку discord_id, если её нет (защита от ошибок)
    try:
        c.execute("ALTER TABLE users ADD COLUMN discord_id TEXT")
    except Exception:
        pass

    # Создаем таблицу ключей (SERIAL вместо AUTOINCREMENT)
    c.execute('''CREATE TABLE IF NOT EXISTS keys
                 (id SERIAL PRIMARY KEY, 
                  key_text TEXT UNIQUE, 
                  key_type TEXT,
                  value INTEGER DEFAULT 0, 
                  used INTEGER DEFAULT 0, 
                  used_by TEXT,
                  used_at TIMESTAMP, 
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    conn.close()
    print("База данных успешно инициализирована")

# Запускаем инициализацию сразу
init_db()

def send_discord(title, desc):
    if not DISCORD_WEBHOOK: return
    data = {"embeds": [{"title": title, "description": desc, "color": 0x3498db}]}
    try: requests.post(DISCORD_WEBHOOK, json=data)
    except: pass

# ============ API ROUTES ============

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    user, pwd = data.get('username'), data.get('password')
    if not user or not pwd: return jsonify({"error": "Пустые поля"}), 400
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (user, pwd))
        conn.commit()
        send_discord('📝 РЕГИСТРАЦИЯ', f'Новый пользователь: **{user}**')
        return jsonify({"success": True})
    except:
        conn.rollback()
        return jsonify({"error": "Имя занято"}), 400
    finally:
        conn.close()

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    user, pwd = data.get('username'), data.get('password')
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT password, balance FROM users WHERE username = %s", (user,))
    res = c.fetchone()
    conn.close()
    if res and res[0] == pwd:
        return jsonify({"success": True, "balance": res[1]})
    return jsonify({"error": "Неверные данные"}), 401

@app.route('/api/add_balance', methods=['POST'])
def add_balance():
    data = request.json
    if data.get('admin_pass') != ADMIN_PASS: return jsonify({"error": "No"}), 403
    user, amt = data.get('username'), data.get('amount', 0)
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + %s WHERE username = %s", (amt, user))
    conn.commit()
    conn.close()
    send_discord('💰 БАЛАНС', f'Админ начислил **{amt}** пользователю **{user}**')
    return jsonify({"success": True})

@app.route('/api/generate_keys', methods=['POST'])
def gen_keys():
    data = request.json
    if data.get('admin_pass') != ADMIN_PASS: return jsonify({"error": "No"}), 403
    count = int(data.get('count', 1))
    ktype = data.get('type', 'balance')
    val = int(data.get('value', 100))
    new_keys = []
    conn = get_conn()
    c = conn.cursor()
    for _ in range(count):
        txt = ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))
        c.execute("INSERT INTO keys (key_text, key_type, value) VALUES (%s, %s, %s)", (txt, ktype, val))
        new_keys.append(txt)
    conn.commit()
    conn.close()
    return jsonify({"keys": new_keys})

@app.route('/api/activate_key', methods=['POST'])
def activate_key():
    data = request.json
    user, ktxt = data.get('username'), data.get('key')
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT key_type, value, used FROM keys WHERE key_text = %s", (ktxt,))
    res = c.fetchone()
    if not res or res[2] == 1:
        conn.close()
        return jsonify({"error": "Ключ невалиден или использован"}), 400
    
    ktype, val, _ = res
    c.execute("UPDATE keys SET used=1, used_by=%s, used_at=%s WHERE key_text=%s", (user, datetime.now(), ktxt))
    if ktype == 'balance':
        c.execute("UPDATE users SET balance = balance + %s WHERE username = %s", (val, user))
    conn.commit()
    conn.close()
    send_discord('🔑 КЛЮЧ', f'**{user}** активировал ключ на **{val}**')
    return jsonify({"success": True, "value": val})

@app.route('/api/update_balance', methods=['POST'])
def update_balance_api():
    data = request.json
    user, bal = data.get('username'), data.get('balance')
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET balance = %s WHERE username = %s", (bal, user))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route('/api/get_stats', methods=['GET'])
def get_stats():
    pwd = request.args.get('admin_pass')
    if pwd != ADMIN_PASS: return "Access Denied", 403
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT username, balance, discord_id FROM users")
    u = c.fetchall()
    c.execute("SELECT key_text, key_type, value, used, used_by FROM keys")
    k = c.fetchall()
    conn.close()
    return jsonify({"users": u, "keys": k})

@app.route('/login/discord')
def discord_login():
    url = f"https://discord.com/api/oauth2/authorize?client_id={DISCORD_CLIENT_ID}&redirect_uri={urllib.parse.quote(SITE_URL+'/login/discord/callback')}&response_type=code&scope=identify"
    return redirect(url)

@app.route('/login/discord/callback')
def discord_callback():
    code = request.args.get('code')
    data = {
        'client_id': DISCORD_CLIENT_ID,
        'client_secret': DISCORD_CLIENT_SECRET,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': f"{SITE_URL}/login/discord/callback"
    }
    r = requests.post('https://discord.com/api/oauth2/token', data=data)
    token = r.json().get('access_token')
    u = requests.get('https://discord.com/api/users/@me', headers={'Authorization': f'Bearer {token}'}).json()
    
    discord_id = u.get('id')
    discord_username = u.get('username')
    
    conn = get_conn()
    c = conn.cursor()
    # Проверяем, есть ли уже такой пользователь
    c.execute("SELECT username, balance FROM users WHERE discord_id = %s", (discord_id,))
    existing = c.fetchone()
    
    if existing:
        username, balance = existing
    else:
        username = discord_username
        balance = 0
        try:
            c.execute("INSERT INTO users (username, discord_id, balance) VALUES (%s, %s, %s)", 
                      (username, discord_id, balance))
            send_discord('📝 РЕГИСТРАЦИЯ', f'**{username}** вошёл через Discord')
        except:
            conn.rollback()
            # Если имя занято, добавим хвостик ID
            username = f"{discord_username}_{discord_id[-4:]}"
            c.execute("INSERT INTO users (username, discord_id, balance) VALUES (%s, %s, %s)", 
                      (username, discord_id, balance))
    
    conn.commit()
    conn.close()
    
    params = urllib.parse.urlencode({'discord_login': '1', 'username': username, 'balance': balance, 'discord_id': discord_id})
    return redirect('/?' + params)

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
