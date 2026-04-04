from flask import Flask, request, jsonify, send_from_directory, redirect
from flask_cors import CORS
import psycopg2
import os
import random
import string
import requests
import urllib.parse
from datetime import datetime

app = Flask(__name__, static_folder='.')
CORS(app)

# Настройки (убедитесь, что они заданы в Railway Variables)
ADMIN_PASS = "34125"
DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1485332673080590429/0ZD2pBkATVamUPhpdriBzBUzvMP5oOKo4H91JO4maCaRGIty1ipE7ZYnrGjL2dSa7-0d"
DATABASE_URL = os.environ.get('DATABASE_URL', '')
UB_TOKEN = os.environ.get('UB_TOKEN', '')
GUILD_ID = '1425098428509061202'
DISCORD_CLIENT_ID = os.environ.get('DISCORD_CLIENT_ID', '')
DISCORD_CLIENT_SECRET = os.environ.get('DISCORD_CLIENT_SECRET', '')
# SITE_URL не должен иметь "/" в конце
SITE_URL = os.environ.get('SITE_URL', 'https://caserequiem-production.up.railway.app').rstrip('/')

if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

def get_conn():
    if not DATABASE_URL:
        raise Exception('DATABASE_URL не задан!')
    return psycopg2.connect(DATABASE_URL)

# ============ UNBELIEVABOAT API ============
UB_BASE = f'https://unbelievaboat.com/api/v1/guilds/{GUILD_ID}'
UB_HEADERS = {'Authorization': UB_TOKEN, 'Content-Type': 'application/json'}

def ub_get_balance(user_id):
    try:
        r = requests.get(f'{UB_BASE}/users/{user_id}', headers=UB_HEADERS, timeout=5)
        if r.status_code == 200:
            return r.json().get('cash', 0)
        return None
    except Exception as e:
        print(f'UB get_balance error: {e}')
        return None

def ub_remove_balance(user_id, amount):
    try:
        r = requests.patch(f'{UB_BASE}/users/{user_id}', headers=UB_HEADERS, json={'cash': -amount}, timeout=5)
        if r.status_code == 200:
            return r.json().get('cash', 0)
        return None
    except Exception as e:
        print(f'UB remove_balance error: {e}')
        return None

def ub_add_balance(user_id, amount):
    try:
        r = requests.patch(f'{UB_BASE}/users/{user_id}', headers=UB_HEADERS, json={'cash': amount}, timeout=5)
        if r.status_code == 200:
            return r.json().get('cash', 0)
        return None
    except Exception as e:
        print(f'UB add_balance error: {e}')
        return None

def send_discord(title, description, color=0x5865F2):
    try:
        data = {"embeds": [{"title": title, "description": description, "color": color,
                            "timestamp": datetime.utcnow().isoformat() + "Z",
                            "footer": {"text": "Clan Case System"}}]}
        requests.post(DISCORD_WEBHOOK, json=data, timeout=5)
    except Exception as e:
        print(f"Discord error: {e}")

# ============ БАЗА ДАННЫХ ============
def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (username TEXT PRIMARY KEY, password TEXT, discord_id TEXT,
                  balance INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    try:
        c.execute("ALTER TABLE users ADD COLUMN discord_id TEXT")
    except:
        pass
    c.execute('''CREATE TABLE IF NOT EXISTS keys
                 (id SERIAL PRIMARY KEY, key_text TEXT UNIQUE, key_type TEXT,
                  value INTEGER DEFAULT 0, used INTEGER DEFAULT 0, used_by TEXT,
                  used_at TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

init_db()

# ============ API МЕТОДЫ ============

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    username, password = data.get('username'), data.get('password')
    if not username or not password:
        return jsonify({'success': False, 'message': 'Заполните все поля'})
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password, balance) VALUES (%s, %s, 0)", (username, password))
        conn.commit()
        send_discord('📝 РЕГИСТРАЦИЯ', f'**{username}** создал аккаунт')
        return jsonify({'success': True})
    except:
        return jsonify({'success': False, 'message': 'Пользователь уже существует'})
    finally:
        conn.close()

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username, password = data.get('username'), data.get('password')
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT balance, discord_id FROM users WHERE username = %s AND password = %s", (username, password))
    user = c.fetchone()
    conn.close()
    if user:
        balance, discord_id = user[0], user[1]
        if discord_id and UB_TOKEN:
            ub_bal = ub_get_balance(discord_id)
            if ub_bal is not None: balance = ub_bal
        return jsonify({'success': True, 'balance': balance})
    return jsonify({'success': False, 'message': 'Ошибка входа'})

@app.route('/api/get_balance', methods=['POST'])
def get_balance():
    username = request.json.get('username')
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT balance, discord_id FROM users WHERE username = %s", (username,))
    row = c.fetchone()
    conn.close()
    if row:
        balance, discord_id = row[0], row[1]
        if discord_id and UB_TOKEN:
            ub_bal = ub_get_balance(discord_id)
            if ub_bal is not None: balance = ub_bal
        return jsonify({'balance': balance})
    return jsonify({'balance': 0})

@app.route('/api/update_balance', methods=['POST'])
def update_balance():
    data = request.json
    username, new_balance = data.get('username'), data.get('balance')
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT balance, discord_id FROM users WHERE username = %s", (username,))
    row = c.fetchone()
    if row:
        old_balance, discord_id = row[0], row[1]
        diff = old_balance - new_balance
        if discord_id and UB_TOKEN and diff > 0:
            res = ub_remove_balance(discord_id, diff)
            if res is not None: new_balance = res
        c.execute("UPDATE users SET balance = %s WHERE username = %s", (new_balance, username))
        conn.commit()
    conn.close()
    return jsonify({'success': True, 'balance': new_balance})

# ============ DISCORD AUTH ============

@app.route('/api/auth/discord')
def auth_discord():
    # Этот URI должен БУКВА В БУКВУ совпадать с тем, что в Discord Developer Portal
    redirect_uri = f"{SITE_URL}/api/auth/callback"
    params = {
        'client_id': DISCORD_CLIENT_ID,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'identify'
    }
    url = f"https://discord.com/api/oauth2/authorize?{urllib.parse.urlencode(params)}"
    return redirect(url)

@app.route('/api/auth/callback')
def auth_callback():
    code = request.args.get('code')
    if not code: return redirect('/?error=no_code')
    
    redirect_uri = f"{SITE_URL}/api/auth/callback"
    
    # Обмен кода на токен
    token_res = requests.post('https://discord.com/api/oauth2/token', data={
        'client_id': DISCORD_CLIENT_ID,
        'client_secret': DISCORD_CLIENT_SECRET,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': redirect_uri,
    }, headers={'Content-Type': 'application/x-www-form-urlencoded'})
    
    if token_res.status_code != 200: return redirect('/?error=token_failed')
    
    access_token = token_res.json().get('access_token')
    user_res = requests.get('https://discord.com/api/users/@me', 
                            headers={'Authorization': f'Bearer {access_token}'})
    
    if user_res.status_code != 200: return redirect('/?error=user_failed')
    
    d_user = user_res.json()
    d_id, d_name = d_user['id'], d_user['username']
    
    balance = ub_get_balance(d_id) or 0
    
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE discord_id = %s", (d_id,))
    existing = c.fetchone()
    
    if existing:
        username = existing[0]
        c.execute("UPDATE users SET balance = %s WHERE discord_id = %s", (balance, d_id))
    else:
        username = d_name
        c.execute("INSERT INTO users (username, discord_id, balance) VALUES (%s, %s, %s)", (username, d_id, balance))
        send_discord('🌐 DISCORD LOGIN', f'**{username}** вошел через Discord')
        
    conn.commit()
    conn.close()
    
    params = urllib.parse.urlencode({'discord_login': '1', 'username': username, 'balance': balance, 'discord_id': d_id})
    return redirect(f'/?{params}')

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
