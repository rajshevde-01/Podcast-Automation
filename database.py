import sqlite3
import os
from datetime import datetime

DB_FILE = "podcast_automation.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Track full podcast episodes we have downloaded/processed
    c.execute('''
        CREATE TABLE IF NOT EXISTS episodes (
            video_id TEXT PRIMARY KEY,
            channel_name TEXT,
            title TEXT,
            processed_date TEXT
        )
    ''')
    
    # Track the extracted shorts
    c.execute('''
        CREATE TABLE IF NOT EXISTS shorts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT,
            start_time REAL,
            end_time REAL,
            short_title TEXT,
            upload_date TEXT,
            upload_url TEXT,
            status TEXT
        )
    ''')
    
    conn.commit()
    conn.close()

def is_episode_processed(video_id: str) -> bool:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT 1 FROM episodes WHERE video_id = ?', (video_id,))
    result = c.fetchone()
    conn.close()
    return result is not None

def log_episode(video_id: str, channel_name: str, title: str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        INSERT OR IGNORE INTO episodes (video_id, channel_name, title, processed_date)
        VALUES (?, ?, ?, ?)
    ''', (video_id, channel_name, title, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def log_short(video_id: str, start_time: float, end_time: float, short_title: str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO shorts (video_id, start_time, end_time, short_title, status)
        VALUES (?, ?, ?, ?, 'GENERATED')
    ''', (video_id, start_time, end_time, short_title))
    short_id = c.lastrowid
    conn.commit()
    conn.close()
    return short_id

def mark_short_uploaded(short_id: int, upload_url: str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        UPDATE shorts 
        SET status = 'UPLOADED', upload_url = ?, upload_date = ?
        WHERE id = ?
    ''', (upload_url, datetime.now().isoformat(), short_id))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized.")
