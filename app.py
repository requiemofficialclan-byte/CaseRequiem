from flask import Flask, request, jsonify, send_from_directory, redirect
from flask_cors import CORS
import psycopg2
from psycopg2 import errors
import os
import random
import string
import requests
from datetime import datetime
import urllib.parse

app = Flask(__name__, static_folder='.')
CORS(app)

ADMIN_PASS = "34125"
DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1485332673080590429/0ZD2pBkATVamUPhpdriBzBUzvMP5oOKo4H91JO4maCaRGIty1ipE7ZYnrGjL2dSa7-0d"
DATABASE_URL = os.environ.get('DATABASE_URL', '')
UB_TOKEN = os.environ.get('UB_TOKEN', '')
GUILD_ID = '1425098428509061202'
DISCORD_CLIENT_ID = os.environ.get('DISCORD_CLIENT_ID', '')
DISCORD_CLIENT_SECRET = os.environ.get('DISCORD_CLIENT_SECRET', '')
# Убедись, что в Railway SITE_URL указан БЕЗ слеша в конце
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
    if not UB_TOKEN: return None
    try:
        r = requests.get(f'{UB_BASE}/users/{user_id}', headers=UB_HEADERS, timeout=5)
        return r.json().get('cash', 0) if r.status_code == 200 else None
    except: return None

def ub_remove_balance(user_id, amount):
    if not UB_TOKEN: return None
    try:
        r = requests.patch(f'{UB_BASE}/users/{user_id}', headers=UB_HEADERS, 
                          json={'cash': -amount}, timeout=5)
        return r.json().get('cash', 0) if r.status_code == 200 else None
    except: return None

def ub_add_balance(user_id, amount):
    if not UB_TOKEN: return None
    try:
        r = requests.patch(f'{UB_BASE}/users/{user_id}', headers=UB_HEADERS, 
                          json={'cash': amount}, timeout=5)
        return r.json().get('cash', 0) if r.status_code == 200 else None
    except: return None

def send_discord(title, description, color=0x5865F2):
    try:
        data = {"embeds": [{"title": title, "description": description, "color": color,
                            "timestamp": datetime.utcnow().isoformat() + "Z",
                            "footer": {"text": "Clan Case System"}}]}
        requests.post(DISCORD_WEBHOOK, json=data, timeout=5)
    except: pass

# ============ БАЗА ДАННЫХ ============
def init_db():
    conn = get_conn()
    conn.autocommit = True # ПРЕДОТВРАЩАЕТ ЗАВИСАНИЕ ТРАНЗАКЦИЙ
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (username TEXT PRIMARY KEY, password TEXT, discord_id TEXT,
                  balance INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    try:
        c.execute("ALTER TABLE users ADD COLUMN discord_id TEXT")
    except: pass
    c.execute('''CREATE TABLE IF NOT EXISTS keys
                 (id SERIAL PRIMARY KEY, key_text TEXT UNIQUE, key_type TEXT,
                  value INTEGER DEFAULT 0, used INTEGER DEFAULT 0, used_by TEXT,
                  used_at TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.close()

init_db()

# ============ РОУТЫ ============

@app.route('/api/auth/discord')
def auth_discord():
    # Исправленное формирование ссылки
    redirect_uri = urllib.parse.quote(f"{SITE_URL}/api/auth/callback")
    url = (f"https://discord.com/api/oauth2/authorize?client_id={DISCORD_CLIENT_ID}"
           f"&redirect_uri={redirect_uri}&response_type=code&scope=identify")
    return redirect(url)

@app.route('/api/auth/callback')
def auth_callback():
    code = request.args.get('code')
    if not code: return redirect('/?error=no_code')
    
    redirect_uri = f"{SITE_URL}/api/auth/callback"
    token_res = requests.post('https://discord.com/api/oauth2/token', data={
        'client_id': DISCORD_CLIENT_ID,
        'client_secret': DISCORD_CLIENT_SECRET,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': redirect_uri,
    }, headers={'Content-Type': 'application/x-www-form-urlencoded'})

    if token_res.status_code != 200: return redirect('/?error=token_failed')
    
    access_token = token_res.json().get('access_token')
    user_data = requests.get('https://discord.com/api/users/@me', 
                            headers={'Authorization': f'Bearer {access_token}'}).json()
    
    discord_id = user_data['id']
    username = user_data['username']
    
    balance = ub_get_balance(discord_id) or 0
    
    conn = get_conn()
    conn.autocommit = True
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE discord_id = %s", (discord_id,))
    existing = c.fetchone()
    
    if existing:
        username = existing[0]
        c.execute("UPDATE users SET balance = %s WHERE discord_id = %s", (balance, discord_id))
    else:
        # Если имя уже занято кем-то другим, добавим ID
        c.execute("SELECT username FROM users WHERE username = %s", (username,))
        if c.fetchone(): username = f"{username}_{discord_id[-4:]}"
        c.execute("INSERT INTO users (username, discord_id, balance) VALUES (%s, %s, %s)", 
                  (username, discord_id, balance))
        send_discord('📝 РЕГИСТРАЦИЯ', f'**{username}** вошёл через Discord')
    
    conn.close()
    params = urllib.parse.urlencode({'discord_login': '1', 'username': username, 'balance': balance, 'discord_id': discord_id})
    return redirect(f'/?{params}')

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    user, pwd = data.get('username'), data.get('password')
    if not user or not pwd: return jsonify({'success': False, 'message': 'Поля пусты'})
    conn = get_conn()
    conn.autocommit = True
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password, balance) VALUES (%s, %s, 0)", (user, pwd))
        send_discord('📝 РЕГИСТРАЦИЯ', f'**{user}** зарегистрировался')
        return jsonify({'success': True})
    except: return jsonify({'success': False, 'message': 'Имя занято'})
    finally: conn.close()

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    user, pwd = data.get('username'), data.get('password')
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT balance, discord_id FROM users WHERE username = %s AND password = %s", (user, pwd))
    res = c.fetchone()
    conn.close()
    if res:
        bal, d_id = res
        if d_id: bal = ub_get_balance(d_id) or bal
        return jsonify({'success': True, 'balance': bal})
    return jsonify({'success': False, 'message': 'Ошибка входа'})

@app.route('/api/use_key', methods=['POST'])
def use_key():
    data = request.json
    ktxt, user = data.get('key'), data.get('username')
    conn = get_conn()
    conn.autocommit = True
    c = conn.cursor()
    c.execute("SELECT key_type, value, used FROM keys WHERE key_text = %s", (ktxt,))
    res = c.fetchone()
    
    if not res or res[2]: 
        conn.close()
        return jsonify({'success': False, 'message': 'Ключ невалиден'})
    
    ktype, kval, _ = res
    c.execute("UPDATE keys SET used=1, used_by=%s, used_at=CURRENT_TIMESTAMP WHERE key_text=%s", (user, ktxt))
    
    if ktype == 'balance':
        c.execute("SELECT discord_id FROM users WHERE username = %s", (user,))
        d_id = c.fetchone()[0]
        if d_id and UB_TOKEN:
            new_bal = ub_add_balance(d_id, kval)
        else:
            c.execute("UPDATE users SET balance = balance + %s WHERE username = %s", (kval, user))
            c.execute("SELECT balance FROM users WHERE username = %s", (user,))
            new_bal = c.fetchone()[0]
        send_discord('💰 КЛЮЧ', f'**{user}** активировал баланс +{kval}')
        conn.close()
        return jsonify({'success': True, 'type': 'balance', 'value': kval, 'balance': new_bal})
    
    conn.close()
    send_discord('🎁 КЛЮЧ', f'**{user}** активировал кейс {ktype}')
    return jsonify({'success': True, 'type': ktype, 'key_count': kval})

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
