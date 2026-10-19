# -*- coding: utf-8 -*-
"""用户与认证：SQLite 存储 + 密码哈希 + token 会话。"""
import os, sqlite3, hashlib, secrets
from fastapi import Header, HTTPException

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "data", "app.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_conn()
    conn.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now'))
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        created_at TEXT DEFAULT (datetime('now'))
    )""")
    conn.commit()
    conn.close()


def hash_password(pw):
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac('sha256', pw.encode(), salt, 100000)
    return salt.hex() + '$' + dk.hex()


def verify_password(pw, stored):
    try:
        salt_hex, dk_hex = stored.split('$', 1)
        dk = hashlib.pbkdf2_hmac('sha256', pw.encode(), bytes.fromhex(salt_hex), 100000)
        return secrets.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


def register(username, password):
    conn = get_conn()
    if conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone():
        conn.close()
        return None
    cur = conn.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)",
                       (username, hash_password(password)))
    uid = cur.lastrowid
    conn.commit()
    conn.close()
    return uid


def login(username, password):
    conn = get_conn()
    row = conn.execute("SELECT id, password_hash FROM users WHERE username=?", (username,)).fetchone()
    conn.close()
    if row and verify_password(password, row['password_hash']):
        return row['id']
    return None


def create_session(user_id):
    token = secrets.token_hex(32)
    conn = get_conn()
    conn.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user_id))
    conn.commit()
    conn.close()
    return token


def user_from_token(token):
    if not token:
        return None
    conn = get_conn()
    row = conn.execute("SELECT user_id FROM sessions WHERE token=?", (token,)).fetchone()
    conn.close()
    return row['user_id'] if row else None


def get_current_user(authorization: str = Header(None)):
    token = ""
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    uid = user_from_token(token)
    if not uid:
        raise HTTPException(401, "未登录或登录已过期")
    return uid
