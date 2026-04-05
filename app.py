from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import psycopg2
import os
import random
import string
import requests
from datetime import datetime

app = Flask(__name__, static_folder='.')
CORS(app)

ADMIN_PASS = "34512"
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
        raise Exception('DATABASE_URL не задан! Добавьте PostgreSQL в Railway.')
    return psycopg2.connect(DATABASE_URL)

def ub_get_balance(discord_id):
    try:
        r = requests.get(f'https://unbelievaboat.com/api/v1/guilds/{GUILD_ID}/users/{discord_id}',
            headers={'Authorization': UB_TOKEN}, timeout=5)
        if r.status_code == 200:
            return r.json().get('cash', 0)
        return None
    except Exception as e:
        print(f'UB get error: {e}')
        return None

def ub_add_balance(discord_id, amount):
    try:
        r = requests.patch(f'https://unbelievaboat.com/api/v1/guilds/{GUILD_ID}/users/{discord_id}',
            headers={'Authorization': UB_TOKEN, 'Content-Type': 'application/json'},
            json={'cash': amount}, timeout=5)
        return r.json().get('cash', 0) if r.status_code == 200 else None
    except Exception as e:
        print(f'UB add error: {e}')
        return None

def ub_remove_balance(discord_id, amount):
    try:
        r = requests.patch(f'https://unbelievaboat.com/api/v1/guilds/{GUILD_ID}/users/{discord_id}',
            headers={'Authorization': UB_TOKEN, 'Content-Type': 'application/json'},
            json={'cash': -amount}, timeout=5)
        return r.json().get('cash', 0) if r.status_code == 200 else None
    except Exception as e:
        print(f'UB remove error: {e}')
        return None

def send_discord(title, description, color=0x5865F2):
    try:
        data = {"embeds": [{"title": title, "description": description, "color": color,
                            "timestamp": datetime.utcnow().isoformat() + "Z",
                            "footer": {"text": "Clan Case System"}}]}
        requests.post(DISCORD_WEBHOOK, json=data, headers={"Content-Type": "application/json"}, timeout=5)
    except Exception as e:
        print(f"Discord error: {e}")

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (username TEXT PRIMARY KEY, password TEXT, discord_id TEXT,
                  balance INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    try:
        c.execute("ALTER TABLE users ADD COLUMN discord_id TEXT")
        conn.commit()
    except:
        conn.rollback()
    c.execute('''CREATE TABLE IF NOT EXISTS keys
                 (id SERIAL PRIMARY KEY, key_text TEXT UNIQUE, key_type TEXT,
                  value INTEGER DEFAULT 0, used INTEGER DEFAULT 0, used_by TEXT,
                  used_at TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

init_db()

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
    username, password = data.get('username'), data.get('password')
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT balance, discord_id FROM users WHERE username = %s AND password = %s", (username, password))
    user = c.fetchone()
    conn.close()
    if user:
        balance = user[0]
        discord_id = user[1]
        if discord_id and UB_TOKEN:
            ub_balance = ub_get_balance(discord_id)
            if ub_balance is not None:
                balance = ub_balance
                conn2 = get_conn()
                c2 = conn2.cursor()
                c2.execute("UPDATE users SET balance = %s WHERE username = %s", (balance, username))
                conn2.commit()
                conn2.close()
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
    if not row:
        return jsonify({'balance': 0})
    balance, discord_id = row
    # Всегда берём актуальный баланс из UnbelievaBoat
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
    return jsonify({'balance': balance})

@app.route('/api/update_balance', methods=['POST'])
def update_balance():
    data = request.json
    username = data.get('username')
    new_balance = data.get('balance')
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT balance, discord_id FROM users WHERE username = %s", (username,))
    row = c.fetchone()
    if row:
        old_balance, discord_id = row
        diff = old_balance - new_balance
        if discord_id and UB_TOKEN and diff > 0:
            result = ub_remove_balance(discord_id, diff)
            if result is not None:
                new_balance = result
    c.execute("UPDATE users SET balance = %s WHERE username = %s", (new_balance, username))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'balance': new_balance})

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
        c.execute("UPDATE users SET balance = balance + %s WHERE username = %s", (key_value, username))
        conn.commit()
        c.execute("SELECT balance FROM users WHERE username = %s", (username,))
        new_balance = c.fetchone()[0]
        conn.close()
        send_discord('💰 КЛЮЧ ИСПОЛЬЗОВАН',
            f'**Пользователь:** {username}\n**Тип:** Баланс\n**Ключ:** ||`{key_text}`||\n**Получено:** +{key_value} монет\n**Новый баланс:** {new_balance} монет',
            color=0xFFD700)
        return jsonify({'success': True, 'type': 'balance', 'value': key_value, 'balance': new_balance})

    conn.commit()
    conn.close()

    msgs = {
        'winter':  ('❄️ КЛЮЧ ИСПОЛЬЗОВАН', 'Зимний кейс', 0x00D4FF),
        'role':    ('🎲 КЛЮЧ ИСПОЛЬЗОВАН', 'Ролевой кейс', 0xFF4757),
        'spring':  ('🌸 КЛЮЧ ИСПОЛЬЗОВАН', 'Весенний кейс', 0x00FFCC),
        'normal':  ('🏆 КЛЮЧ ИСПОЛЬЗОВАН', 'Обычный кейс', 0xFFD700),
        'starter': ('🌟 КЛЮЧ ИСПОЛЬЗОВАН', 'Стартовый кейс', 0xB44FFF),
    }
    if key_type in msgs:
        title, type_name, color = msgs[key_type]
        key_count = key_value if key_value and key_value > 0 else 1
        count_str = f' x{key_count}' if key_count > 1 else ''
        send_discord(title,
            f'**Пользователь:** {username}\n**Тип:** {type_name}{count_str}\n**Ключ:** ||`{key_text}`||',
            color=color)
        return jsonify({'success': True, 'type': key_type, 'key_count': key_count})

    return jsonify({'success': False})

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
        # Сохраняем key_count в поле value
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
    c.execute("SELECT username, balance FROM users ORDER BY balance DESC")
    users = c.fetchall()
    conn.close()
    return jsonify({'success': True, 'users': [{'username': u[0], 'balance': u[1]} for u in users]})

@app.route('/api/admin/add_balance', methods=['POST'])
def admin_add_balance():
    data = request.json
    if data.get('password') != ADMIN_PASS:
        return jsonify({'success': False})
    username, amount = data.get('username'), data.get('amount', 0)
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT discord_id FROM users WHERE username = %s", (username,))
    row = c.fetchone()
    discord_id = row[0] if row else None
    if discord_id and UB_TOKEN:
        new_bal = ub_add_balance(discord_id, amount)
        if new_bal is not None:
            c.execute("UPDATE users SET balance = %s WHERE username = %s", (new_bal, username))
        else:
            c.execute("UPDATE users SET balance = balance + %s WHERE username = %s", (amount, username))
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
    c.execute("SELECT balance FROM users WHERE username = %s", (username,))
    user = c.fetchone()
    if not user:
        conn.close()
        return jsonify({'success': False, 'message': 'Пользователь не найден'})
    new_balance = max(0, user[0] - amount)
    actual = user[0] - new_balance
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


import urllib.parse

@app.route('/api/auth/discord')
def auth_discord():
    redirect_uri = SITE_URL + '/api/auth/callback'
    url = ('https://discord.com/api/oauth2/authorize'
           '?client_id=' + DISCORD_CLIENT_ID +
           '&redirect_uri=' + urllib.parse.quote(redirect_uri, safe='') +
           '&response_type=code&scope=identify')
    from flask import redirect as flask_redirect
    return flask_redirect(url)

@app.route('/api/auth/callback')
def auth_callback():
    from flask import redirect as flask_redirect
    code = request.args.get('code')
    if not code:
        return flask_redirect('/?error=no_code')
    redirect_uri = SITE_URL + '/api/auth/callback'
    token_res = requests.post('https://discord.com/api/oauth2/token', data={
        'client_id': DISCORD_CLIENT_ID, 'client_secret': DISCORD_CLIENT_SECRET,
        'grant_type': 'authorization_code', 'code': code, 'redirect_uri': redirect_uri,
    }, headers={'Content-Type': 'application/x-www-form-urlencoded'}, timeout=10)
    if token_res.status_code != 200:
        return flask_redirect('/?error=token_failed')
    access_token = token_res.json().get('access_token')
    user_res = requests.get('https://discord.com/api/users/@me',
        headers={'Authorization': 'Bearer ' + access_token}, timeout=10)
    if user_res.status_code != 200:
        return flask_redirect('/?error=user_failed')
    discord_user = user_res.json()
    discord_id = discord_user['id']
    discord_username = discord_user['username']
    balance = 0
    if UB_TOKEN:
        ub_bal = ub_get_balance(discord_id)
        if ub_bal is not None:
            balance = ub_bal
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE discord_id = %s", (discord_id,))
    existing = c.fetchone()
    if existing:
        username = existing[0]
        c.execute("UPDATE users SET balance = %s WHERE discord_id = %s", (balance, discord_id))
    else:
        username = discord_username
        c.execute("SELECT username FROM users WHERE username = %s", (username,))
        if c.fetchone():
            username = discord_username + '_' + discord_id[-4:]
        try:
            c.execute("INSERT INTO users (username, discord_id, balance) VALUES (%s, %s, %s)",
                      (username, discord_id, balance))
            send_discord('📝 РЕГИСТРАЦИЯ', f'**{username}** вошёл через Discord')
        except Exception as e:
            conn.rollback()
            conn.close()
            return flask_redirect('/?error=register_failed')
    conn.commit()
    conn.close()
    params = urllib.parse.urlencode({'discord_login': '1', 'username': username, 'balance': balance})
    return flask_redirect('/?' + params)

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("🚀 СЕРВЕР ЗАПУЩЕН")
    app.run(host='0.0.0.0', port=port, debug=False)
