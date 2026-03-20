from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import sqlite3
import random
import string
import socket
import requests
from datetime import datetime

app = Flask(__name__, static_folder='.')
CORS(app)

# ============ КОНФИГУРАЦИЯ ============
ADMIN_PASS = "34125"
DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1483941280248496210/QHWJYcnhPD8Voht5mElw7KVNX-vr4yU5gHQrFoAwTE14vqB9MNnIISuTCjOfMYCEq0cA"

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return '127.0.0.1'

def send_discord(title, description, color=0x5865F2):
    try:
        data = {
            "embeds": [{
                "title": title,
                "description": description,
                "color": color,
                "timestamp": datetime.utcnow().isoformat(),
                "footer": {"text": "Clan Case System"}
            }]
        }
        requests.post(DISCORD_WEBHOOK, json=data)
    except Exception as e:
        print(f"Discord error: {e}")

# ============ БАЗА ДАННЫХ ============
def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (username TEXT PRIMARY KEY,
                  password TEXT,
                  balance INTEGER DEFAULT 0,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS keys
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  key_text TEXT UNIQUE,
                  key_type TEXT,
                  value INTEGER DEFAULT 0,
                  used INTEGER DEFAULT 0,
                  used_by TEXT,
                  used_at TIMESTAMP,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

init_db()

# ============ ПОЛЬЗОВАТЕЛИ ============
@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({'success': False, 'message': 'Заполните все поля'})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    try:
        c.execute("INSERT INTO users (username, password, balance) VALUES (?, ?, 0)",
                  (username, password))
        conn.commit()
        send_discord('📝 НОВАЯ РЕГИСТРАЦИЯ', f'**{username}** зарегистрировался')
        conn.close()
        return jsonify({'success': True})
    except:
        conn.close()
        return jsonify({'success': False, 'message': 'Пользователь уже существует'})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE username = ? AND password = ?", (username, password))
    user = c.fetchone()
    conn.close()
    
    if user:
        send_discord('🔐 ВХОД', f'**{username}** вошел в систему')
        return jsonify({'success': True, 'balance': user[0]})
    return jsonify({'success': False, 'message': 'Неверный логин или пароль'})

@app.route('/api/get_balance', methods=['POST'])
def get_balance():
    data = request.json
    username = data.get('username')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE username = ?", (username,))
    balance = c.fetchone()
    conn.close()
    return jsonify({'balance': balance[0] if balance else 0})

@app.route('/api/update_balance', methods=['POST'])
def update_balance():
    data = request.json
    username = data.get('username')
    new_balance = data.get('balance')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("UPDATE users SET balance = ? WHERE username = ?", (new_balance, username))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ============ КЛЮЧИ ============
@app.route('/api/use_key', methods=['POST'])
def use_key():
    data = request.json
    key_text = data.get('key')
    username = data.get('username')
    won_item = data.get('won_item', '')  # предмет который выпал (присылает фронтенд)
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT key_type, value, used FROM keys WHERE key_text = ?", (key_text,))
    key = c.fetchone()
    
    if not key:
        conn.close()
        return jsonify({'success': False, 'message': '❌ Ключ не найден'})
    
    key_type, value, used = key
    
    if used:
        conn.close()
        return jsonify({'success': False, 'message': '❌ Ключ уже использован'})
    
    if key_type == 'balance':
        c.execute("UPDATE users SET balance = balance + ? WHERE username = ?", (value, username))
        c.execute("UPDATE keys SET used = 1, used_by = ?, used_at = CURRENT_TIMESTAMP WHERE key_text = ?", (username, key_text))
        conn.commit()
        c.execute("SELECT balance FROM users WHERE username = ?", (username,))
        new_balance = c.fetchone()[0]
        conn.close()
        send_discord('💰 КЛЮЧ ИСПОЛЬЗОВАН',
            f'**Пользователь:** {username}\n'
            f'**Тип:** Баланс\n'
            f'**Ключ:** `{key_text}`\n'
            f'**Получено:** +{value} монет\n'
            f'**Новый баланс:** {new_balance} монет',
            color=0xFFD700)
        return jsonify({'success': True, 'type': 'balance', 'value': value, 'balance': new_balance})
    
    elif key_type == 'winter':
        c.execute("UPDATE keys SET used = 1, used_by = ?, used_at = CURRENT_TIMESTAMP WHERE key_text = ?", (username, key_text))
        conn.commit()
        conn.close()
        send_discord('❄️ КЛЮЧ ИСПОЛЬЗОВАН',
            f'**Пользователь:** {username}\n'
            f'**Тип:** Зимний кейс\n'
            f'**Ключ:** `{key_text}`\n'
            f'**Выпало:** {won_item if won_item else "неизвестно"}',
            color=0x00D4FF)
        return jsonify({'success': True, 'type': 'winter'})
    
    elif key_type == 'role':
        c.execute("UPDATE keys SET used = 1, used_by = ?, used_at = CURRENT_TIMESTAMP WHERE key_text = ?", (username, key_text))
        conn.commit()
        conn.close()
        send_discord('🎲 КЛЮЧ ИСПОЛЬЗОВАН',
            f'**Пользователь:** {username}\n'
            f'**Тип:** Ролевой кейс\n'
            f'**Ключ:** `{key_text}`\n'
            f'**Выпало:** {won_item if won_item else "неизвестно"}',
            color=0xFF4757)
        return jsonify({'success': True, 'type': 'role'})

    elif key_type == 'spring':
        c.execute("UPDATE keys SET used = 1, used_by = ?, used_at = CURRENT_TIMESTAMP WHERE key_text = ?", (username, key_text))
        conn.commit()
        conn.close()
        send_discord('🌸 КЛЮЧ ИСПОЛЬЗОВАН',
            f'**Пользователь:** {username}\n'
            f'**Тип:** Весенний кейс (по ключу)\n'
            f'**Ключ:** `{key_text}`\n'
            f'**Выпало:** {won_item if won_item else "неизвестно"}',
            color=0x00FFCC)
        return jsonify({'success': True, 'type': 'spring'})

    conn.close()
    return jsonify({'success': False})

# ============ АДМИН ============
@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.json
    password = data.get('password')
    return jsonify({'success': password == ADMIN_PASS})

@app.route('/api/admin/create_key', methods=['POST'])
def admin_create_key():
    data = request.json
    if data.get('password') != ADMIN_PASS:
        return jsonify({'success': False})
    
    key_type = data.get('key_type')
    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    if key_type == 'balance':
        value = data.get('value', 1000)
        while True:
            random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            key_text = f"BAL-{value}-{random_part}"
            c.execute("SELECT key_text FROM keys WHERE key_text = ?", (key_text,))
            if not c.fetchone():
                break
        c.execute("INSERT INTO keys (key_text, key_type, value) VALUES (?, ?, ?)",
                  (key_text, key_type, value))
        conn.commit()
        conn.close()
        send_discord('🔑 КЛЮЧ СОЗДАН', f'**Тип:** Баланс\n**Сумма:** {value} монет\n**Ключ:** `{key_text}`', color=0xFFD700)
        return jsonify({'success': True, 'key': key_text})

    elif key_type == 'winter':
        while True:
            random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            key_text = f"WINTER-{random_part}"
            c.execute("SELECT key_text FROM keys WHERE key_text = ?", (key_text,))
            if not c.fetchone():
                break
        c.execute("INSERT INTO keys (key_text, key_type) VALUES (?, ?)", (key_text, key_type))
        conn.commit()
        conn.close()
        send_discord('🔑 КЛЮЧ СОЗДАН', f'**Тип:** Зимний кейс\n**Ключ:** `{key_text}`', color=0x00D4FF)
        return jsonify({'success': True, 'key': key_text})

    elif key_type == 'role':
        while True:
            random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            key_text = f"ROLE-{random_part}"
            c.execute("SELECT key_text FROM keys WHERE key_text = ?", (key_text,))
            if not c.fetchone():
                break
        c.execute("INSERT INTO keys (key_text, key_type) VALUES (?, ?)", (key_text, key_type))
        conn.commit()
        conn.close()
        send_discord('🔑 КЛЮЧ СОЗДАН', f'**Тип:** Ролевой кейс\n**Ключ:** `{key_text}`', color=0xFF4757)
        return jsonify({'success': True, 'key': key_text})

    elif key_type == 'spring':
        while True:
            random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            key_text = f"SPRING-{random_part}"
            c.execute("SELECT key_text FROM keys WHERE key_text = ?", (key_text,))
            if not c.fetchone():
                break
        c.execute("INSERT INTO keys (key_text, key_type) VALUES (?, ?)", (key_text, key_type))
        conn.commit()
        conn.close()
        send_discord('🔑 КЛЮЧ СОЗДАН', f'**Тип:** Весенний кейс\n**Ключ:** `{key_text}`', color=0x00FFCC)
        return jsonify({'success': True, 'key': key_text})

    conn.close()
    return jsonify({'success': False})

@app.route('/api/admin/get_stats', methods=['POST'])
def admin_get_stats():
    data = request.json
    if data.get('password') != ADMIN_PASS:
        return jsonify({'success': False})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM keys")
    total_keys = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM keys WHERE used = 1")
    used_keys = c.fetchone()[0]
    conn.close()
    
    return jsonify({
        'success': True,
        'users': users,
        'total_keys': total_keys,
        'used_keys': used_keys,
        'available_keys': total_keys - used_keys
    })

@app.route('/api/admin/get_keys', methods=['POST'])
def admin_get_keys():
    data = request.json
    if data.get('password') != ADMIN_PASS:
        return jsonify({'success': False})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT key_text, key_type, value, used, used_by, used_at FROM keys ORDER BY rowid DESC")
    keys = c.fetchall()
    conn.close()
    
    return jsonify({
        'success': True,
        'keys': [{
            'key': k[0],
            'type': k[1],
            'value': k[2],
            'used': bool(k[3]),
            'used_by': k[4],
            'used_at': k[5]
        } for k in keys]
    })

@app.route('/api/admin/get_users', methods=['POST'])
def admin_get_users():
    data = request.json
    if data.get('password') != ADMIN_PASS:
        return jsonify({'success': False})
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT username, balance FROM users ORDER BY balance DESC")
    users = c.fetchall()
    conn.close()
    
    return jsonify({
        'success': True,
        'users': [{'username': u[0], 'balance': u[1]} for u in users]
    })

@app.route('/api/admin/add_balance', methods=['POST'])
def admin_add_balance():
    data = request.json
    if data.get('password') != ADMIN_PASS:
        return jsonify({'success': False})
    
    username = data.get('username')
    amount = data.get('amount', 0)
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + ? WHERE username = ?", (amount, username))
    conn.commit()
    conn.close()
    
    send_discord('💰 ПОПОЛНЕНИЕ', f'Админ добавил **{amount}** монет пользователю **{username}**')
    return jsonify({'success': True})

@app.route('/api/admin/delete_user', methods=['POST'])
def admin_delete_user():
    data = request.json
    if data.get('password') != ADMIN_PASS:
        return jsonify({'success': False})
    
    username = data.get('username')
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE username = ?", (username,))
    conn.commit()
    conn.close()
    
    send_discord('🗑️ УДАЛЕНИЕ', f'Админ удалил пользователя **{username}**')
    return jsonify({'success': True})


@app.route('/api/report_win', methods=['POST'])
def report_win():
    data = request.json
    username = data.get('username', '?')
    key = data.get('key', '')
    won_item = data.get('won_item', '?')
    case_type = data.get('case_type', '?')
    paid_coins = data.get('paid_coins', 0)  # если открыл за монеты

    icons = {'winter': '❄️', 'role': '🎲', 'spring': '🌸'}
    colors = {'winter': 0x00D4FF, 'role': 0xFF4757, 'spring': 0x00FFCC}
    icon = icons.get(case_type, '🎁')
    color = colors.get(case_type, 0x00FFCC)

    if paid_coins:
        method = f'💰 За монеты ({paid_coins} монет)'
        key_line = ''
    else:
        method = f'🔑 По ключу'
        key_line = f'\n**Ключ:** `{key}`'

    send_discord(f'{icon} РЕЗУЛЬТАТ КЕЙСА',
        f'**Пользователь:** {username}\n'
        f'**Кейс:** {case_type}\n'
        f'**Способ:** {method}'
        f'{key_line}\n'
        f'**Выпало:** {won_item}',
        color=color)
    return jsonify({'success': True})

@app.route('/api/test', methods=['GET'])
def test():
    return jsonify({'status': 'ok', 'ip': get_local_ip()})

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

if __name__ == '__main__':
    ip = get_local_ip()
    print("="*60)
    print("🚀 СЕРВЕР ЗАПУЩЕН")
    print(f"📌 На ПК: http://localhost:5000")
    print(f"📌 В сети: http://{ip}:5000")
    print(f"🔐 Пароль админа: {ADMIN_PASS}")
    print("="*60)
    app.run(host='0.0.0.0', port=5000, debug=True)