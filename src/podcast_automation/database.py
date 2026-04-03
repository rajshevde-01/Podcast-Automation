import sqlite3
from typing import Optional, List
from .config import settings
from .models import Short
from loguru import logger

class DatabaseManager:
    def __init__(self, db_path: str = settings.DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Table for tracking processed episodes
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS episodes (
                    video_id TEXT PRIMARY KEY,
                    podcast_name TEXT,
                    title TEXT,
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Table for tracking generated shorts
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS shorts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    episode_id TEXT,
                    start_time REAL,
                    end_time REAL,
                    title TEXT,
                    video_url TEXT,
                    is_uploaded BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (episode_id) REFERENCES episodes(video_id)
                )
            """)
            conn.commit()
            logger.info("Database initialized.")

    def is_episode_processed(self, video_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM episodes WHERE video_id = ?", (video_id,))
            return cursor.fetchone() is not None

    def log_episode(self, video_id: str, podcast_name: str, title: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO episodes (video_id, podcast_name, title) VALUES (?, ?, ?)",
                (video_id, podcast_name, title)
            )
            conn.commit()

    def log_short(self, episode_id: str, start_time: float, end_time: float, title: str) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO shorts (episode_id, start_time, end_time, title) VALUES (?, ?, ?, ?)",
                (episode_id, start_time, end_time, title)
            )
            conn.commit()
            return cursor.lastrowid

    def mark_short_uploaded(self, short_id: int, video_url: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE shorts SET is_uploaded = 1, video_url = ? WHERE id = ?",
                (video_url, short_id)
            )
            conn.commit()

    def get_last_uploaded_short(self) -> Optional[dict]:
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM shorts WHERE is_uploaded = 1 ORDER BY created_at DESC LIMIT 1")
            row = cursor.fetchone()
            return dict(row) if row else None

db_manager = DatabaseManager()
