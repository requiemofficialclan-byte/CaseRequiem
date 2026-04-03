from flask import Flask, request, jsonify, send_from_directory, redirect
from flask_cors import CORS
import psycopg2
import os
import random
import string
import requests
from datetime import datetime

app = Flask(__name__, static_folder='.')
CORS(app)

ADMIN_PASS = "34125"
DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1485332673080590429/0ZD2pBkATVamUPhpdriBzBUzvMP5oOKo4H91JO4maCaRGIty1ipE7ZYnrGjL2dSa7-0d"
DATABASE_URL = os.environ.get('DATABASE_URL', '')
UB_TOKEN = os.environ.get('UB_TOKEN', '')
GUILD_ID = '1425098428509061202'

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
    """Получить баланс пользователя из UnbelievaBoat"""
    try:
        r = requests.get(f'{UB_BASE}/users/{user_id}', headers=UB_HEADERS, timeout=5)
        if r.status_code == 200:
            data = r.json()
            return data.get('cash', 0)
        return None
    except Exception as e:
        print(f'UB get_balance error: {e}')
        return None

def ub_remove_balance(user_id, amount):
    """Снять монеты у пользователя через UnbelievaBoat"""
    try:
        r = requests.patch(
            f'{UB_BASE}/users/{user_id}',
            headers=UB_HEADERS,
            json={'cash': -amount},
            timeout=5
        )
        if r.status_code == 200:
            return r.json().get('cash', 0)
        print(f'UB remove error: {r.status_code} {r.text}')
        return None
    except Exception as e:
        print(f'UB remove_balance error: {e}')
        return None

def ub_add_balance(user_id, amount):
    """Добавить монеты пользователю через UnbelievaBoat"""
    try:
        r = requests.patch(
            f'{UB_BASE}/users/{user_id}',
            headers=UB_HEADERS,
            json={'cash': amount},
            timeout=5
        )
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
        requests.post(DISCORD_WEBHOOK, json=data, headers={"Content-Type": "application/json"}, timeout=5)
    except Exception as e:
        print(f"Discord error: {e}")

# ============ БАЗА ДАННЫХ (только для ключей и пользователей) ============
def init_db():
    conn = get_conn()
    c = conn.cursor()
    # Добавляем discord_id в таблицу users
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (username TEXT PRIMARY KEY,
                  password TEXT,
                  discord_id TEXT,
                  balance INTEGER DEFAULT 0,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    # Добавляем колонку discord_id если её нет
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

# ============ ПОЛЬЗОВАТЕЛИ ============
@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({'success': False, 'message': 'Заполните все поля'})
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password, balance) VALUES (%s, %s, 0)", (username, password))
        conn.commit()
        send_discord('📝 НОВАЯ РЕГИСТРАЦИЯ', f'**{username}** зарегистрировался')
        return jsonify({'success': True})
    except:
        conn.rollback()
        return jsonify({'success': False, 'message': 'Пользователь уже существует'})
    finally:
        conn.close()

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT balance, discord_id FROM users WHERE username = %s AND password = %s", (username, password))
    user = c.fetchone()
    conn.close()
    if user:
        balance = user[0]
        discord_id = user[1]
        # Если есть discord_id — берём баланс из UnbelievaBoat
        if discord_id and UB_TOKEN:
            ub_balance = ub_get_balance(discord_id)
            if ub_balance is not None:
                balance = ub_balance
                # Синхронизируем в БД
                conn2 = get_conn()
                c2 = conn2.cursor()
                c2.execute("UPDATE users SET balance = %s WHERE username = %s", (balance, username))
                conn2.commit()
                conn2.close()
        send_discord('🔐 ВХОД', f'**{username}** вошел в систему')
        return jsonify({'success': True, 'balance': balance})
    return jsonify({'success': False, 'message': 'Неверный логин или пароль'})

@app.route('/api/get_balance', methods=['POST'])
def get_balance():
    data = request.json
    username = data.get('username')
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT balance, discord_id FROM users WHERE username = %s", (username,))
    row = c.fetchone()
    conn.close()
    if row:
        balance = row[0]
        discord_id = row[1]
        if discord_id and UB_TOKEN:
            ub_balance = ub_get_balance(discord_id)
            if ub_balance is not None:
                balance = ub_balance
        return jsonify({'balance': balance})
    return jsonify({'balance': 0})

@app.route('/api/update_balance', methods=['POST'])
def update_balance():
    """Списание монет — через UnbelievaBoat если есть discord_id"""
    data = request.json
    username = data.get('username')
    new_balance = data.get('balance')
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT balance, discord_id FROM users WHERE username = %s", (username,))
    row = c.fetchone()
    if row:
        old_balance = row[0]
        discord_id = row[1]
        diff = old_balance - new_balance  # сколько нужно снять
        if discord_id and UB_TOKEN and diff > 0:
            # Снимаем через UnbelievaBoat
            result = ub_remove_balance(discord_id, diff)
            if result is not None:
                new_balance = result
        c.execute("UPDATE users SET balance = %s WHERE username = %s", (new_balance, username))
        conn.commit()
    conn.close()
    return jsonify({'success': True, 'balance': new_balance})

# ============ ПРИВЯЗКА DISCORD ID ============
@app.route('/api/link_discord', methods=['POST'])
def link_discord():
    """Привязать Discord ID к аккаунту"""
    data = request.json
    username = data.get('username')
    discord_id = data.get('discord_id')
    if not username or not discord_id:
        return jsonify({'success': False})
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET discord_id = %s WHERE username = %s", (discord_id, username))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ============ КЛЮЧИ ============
@app.route('/api/use_key', methods=['POST'])
def use_key():
    data = request.json
    key_text = data.get('key')
    username = data.get('username')
    won_item = data.get('won_item', '')
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT key_type, value, used FROM keys WHERE key_text = %s", (key_text,))
    key = c.fetchone()
    if not key:
        conn.close()
        return jsonify({'success': False, 'message': '❌ Ключ не найден'})
    key_type, key_value, used = key
    if used:
        conn.close()
        return jsonify({'success': False, 'message': '❌ Ключ уже использован'})

    c.execute("UPDATE keys SET used = 1, used_by = %s, used_at = CURRENT_TIMESTAMP WHERE key_text = %s", (username, key_text))

    if key_type == 'balance':
        # Добавляем монеты — через UB если привязан
        c.execute("SELECT discord_id FROM users WHERE username = %s", (username,))
        row = c.fetchone()
        discord_id = row[0] if row else None
        if discord_id and UB_TOKEN:
            new_balance = ub_add_balance(discord_id, key_value)
        else:
            c.execute("UPDATE users SET balance = balance + %s WHERE username = %s", (key_value, username))
            c.execute("SELECT balance FROM users WHERE username = %s", (username,))
            new_balance = c.fetchone()[0]
        conn.commit()
        conn.close()
        send_discord('💰 КЛЮЧ ИСПОЛЬЗОВАН',
            f'**Пользователь:** {username}\n**Тип:** Баланс\n**Ключ:** ||`{key_text}`||\n**Получено:** +{key_value} монет\n**Новый баланс:** {new_balance} монет',
            color=0xFFD700)
        return jsonify({'success': True, 'type': 'balance', 'value': key_value, 'balance': new_balance})

    msgs = {
        'winter':  ('❄️ КЛЮЧ ИСПОЛЬЗОВАН', 'Зимний кейс', 0x00D4FF),
        'role':    ('🎲 КЛЮЧ ИСПОЛЬЗОВАН', 'Ролевой кейс', 0xFF4757),
        'spring':  ('🌸 КЛЮЧ ИСПОЛЬЗОВАН', 'Весенний кейс', 0x00FFCC),
        'normal':  ('🏆 КЛЮЧ ИСПОЛЬЗОВАН', 'Обычный кейс', 0xFFD700),
        'starter': ('🌟 КЛЮЧ ИСПОЛЬЗОВАН', 'Стартовый кейс', 0xB44FFF),
    }
    if key_type in msgs:
        key_count = key_value if key_value and key_value > 0 else 1
        conn.commit()
        conn.close()
        title, type_name, color = msgs[key_type]
        count_str = f' x{key_count}' if key_count > 1 else ''
        send_discord(title,
            f'**Пользователь:** {username}\n**Тип:** {type_name}{count_str}\n**Ключ:** ||`{key_text}`||',
            color=color)
        return jsonify({'success': True, 'type': key_type, 'key_count': key_count})

    conn.close()
    return jsonify({'success': False})

# ============ АДМИН ============
@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    return jsonify({'success': request.json.get('password') == ADMIN_PASS})

def gen_key(prefix, c):
    while True:
        part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        key_text = f"{prefix}-{part}"
        c.execute("SELECT key_text FROM keys WHERE key_text = %s", (key_text,))
        if not c.fetchone():
            return key_text

@app.route('/api/admin/create_key', methods=['POST'])
def admin_create_key():
    data = request.json
    if data.get('password') != ADMIN_PASS:
        return jsonify({'success': False})
    key_type = data.get('key_type')
    conn = get_conn()
    c = conn.cursor()
    prefixes = {'winter': 'WINTER', 'role': 'ROLE', 'spring': 'SPRING', 'normal': 'NORMAL', 'starter': 'STARTER'}
    colors   = {'winter': 0x00D4FF, 'role': 0xFF4757, 'spring': 0x00FFCC, 'normal': 0xFFD700, 'starter': 0xB44FFF}
    names    = {'winter': 'Зимний кейс', 'role': 'Ролевой кейс', 'spring': 'Весенний кейс', 'normal': 'Обычный кейс', 'starter': 'Стартовый кейс'}

    if key_type == 'balance':
        value = data.get('value', 1000)
        key_text = gen_key(f"BAL-{value}", c)
        c.execute("INSERT INTO keys (key_text, key_type, value) VALUES (%s, %s, %s)", (key_text, key_type, value))
        conn.commit()
        conn.close()
        send_discord('🔑 КЛЮЧ СОЗДАН', f'**Тип:** Баланс\n**Сумма:** {value} монет\n**Ключ:** ||`{key_text}`||', color=0xFFD700)
        return jsonify({'success': True, 'key': key_text})
    elif key_type in prefixes:
        key_count = min(10, max(1, int(data.get('key_count', 1) or 1)))
        key_text = gen_key(prefixes[key_type], c)
        c.execute("INSERT INTO keys (key_text, key_type, value) VALUES (%s, %s, %s)", (key_text, key_type, key_count))
        conn.commit()
        conn.close()
        count_str = f' x{key_count}' if key_count > 1 else ''
        send_discord('🔑 КЛЮЧ СОЗДАН', f'**Тип:** {names[key_type]}{count_str}\n**Ключ:** ||`{key_text}`||', color=colors[key_type])
        return jsonify({'success': True, 'key': key_text})

    conn.close()
    return jsonify({'success': False})

@app.route('/api/admin/get_stats', methods=['POST'])
def admin_get_stats():
    if request.json.get('password') != ADMIN_PASS:
        return jsonify({'success': False})
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users"); users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM keys"); total_keys = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM keys WHERE used = 1"); used_keys = c.fetchone()[0]
    conn.close()
    return jsonify({'success': True, 'users': users, 'total_keys': total_keys,
                    'used_keys': used_keys, 'available_keys': total_keys - used_keys})

@app.route('/api/admin/get_keys', methods=['POST'])
def admin_get_keys():
    if request.json.get('password') != ADMIN_PASS:
        return jsonify({'success': False})
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT key_text, key_type, value, used, used_by, used_at FROM keys ORDER BY id DESC")
    keys = c.fetchall()
    conn.close()
    return jsonify({'success': True, 'keys': [
        {'key': k[0], 'type': k[1], 'value': k[2], 'used': bool(k[3]),
         'used_by': k[4], 'used_at': str(k[5]) if k[5] else None} for k in keys]})

@app.route('/api/admin/get_users', methods=['POST'])
def admin_get_users():
    if request.json.get('password') != ADMIN_PASS:
        return jsonify({'success': False})
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT username, balance, discord_id FROM users ORDER BY balance DESC")
    users = c.fetchall()
    conn.close()
    return jsonify({'success': True, 'users': [
        {'username': u[0], 'balance': u[1], 'discord_id': u[2]} for u in users]})

@app.route('/api/admin/add_balance', methods=['POST'])
def admin_add_balance():
    data = request.json
    if data.get('password') != ADMIN_PASS:
        return jsonify({'success': False})
    username = data.get('username')
    amount = data.get('amount', 0)
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT discord_id FROM users WHERE username = %s", (username,))
    row = c.fetchone()
    discord_id = row[0] if row else None
    if discord_id and UB_TOKEN:
        new_balance = ub_add_balance(discord_id, amount)
        if new_balance is not None:
            c.execute("UPDATE users SET balance = %s WHERE username = %s", (new_balance, username))
    else:
        c.execute("UPDATE users SET balance = balance + %s WHERE username = %s", (amount, username))
    conn.commit()
    conn.close()
    send_discord('💰 ПОПОЛНЕНИЕ', f'Админ добавил **{amount}** монет пользователю **{username}**')
    return jsonify({'success': True})

@app.route('/api/admin/remove_balance', methods=['POST'])
def admin_remove_balance():
    data = request.json
    if data.get('password') != ADMIN_PASS:
        return jsonify({'success': False})
    username = data.get('username')
    amount = data.get('amount', 0)
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT balance, discord_id FROM users WHERE username = %s", (username,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({'success': False, 'message': 'Пользователь не найден'})
    old_balance, discord_id = row
    if discord_id and UB_TOKEN:
        new_balance = ub_remove_balance(discord_id, amount)
        if new_balance is None:
            new_balance = max(0, old_balance - amount)
    else:
        new_balance = max(0, old_balance - amount)
    actual = old_balance - new_balance
    c.execute("UPDATE users SET balance = %s WHERE username = %s", (new_balance, username))
    conn.commit()
    conn.close()
    send_discord('➖ СНЯТИЕ МОНЕТ', f'Админ снял **{actual}** монет у **{username}**\n**Остаток:** {new_balance} монет')
    return jsonify({'success': True})

@app.route('/api/admin/delete_user', methods=['POST'])
def admin_delete_user():
    data = request.json
    if data.get('password') != ADMIN_PASS:
        return jsonify({'success': False})
    username = data.get('username')
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE username = %s", (username,))
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
    paid_coins = data.get('paid_coins', 0)
    icons  = {'winter': '❄️', 'role': '🎲', 'spring': '🌸', 'normal': '🏆', 'starter': '🌟'}
    colors = {'winter': 0x00D4FF, 'role': 0xFF4757, 'spring': 0x00FFCC, 'normal': 0xFFD700, 'starter': 0xB44FFF}
    icon = icons.get(case_type, '🎁')
    color = colors.get(case_type, 0x00FFCC)
    if paid_coins:
        method = f'💰 За монеты ({paid_coins} монет)'
        key_line = ''
    else:
        method = '🔑 По ключу'
        key_line = f'\n**Ключ:** ||`{key}`||'
    send_discord(f'{icon} РЕЗУЛЬТАТ КЕЙСА',
        f'**Пользователь:** {username}\n**Кейс:** {case_type}\n**Способ:** {method}{key_line}\n**Выпало:** {won_item}',
        color=color)
    return jsonify({'success': True})

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("🚀 СЕРВЕР ЗАПУЩЕН")
    app.run(host='0.0.0.0', port=port, debug=False)
