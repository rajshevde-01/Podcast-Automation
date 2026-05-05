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
                    license_type TEXT DEFAULT 'youtube',
                    copyright_risk TEXT DEFAULT 'medium',
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
            # Table for caching channel info and copyright status
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS channels (
                    channel_id TEXT PRIMARY KEY,
                    name TEXT,
                    subscriber_count INTEGER DEFAULT 0,
                    total_videos INTEGER DEFAULT 0,
                    country TEXT,
                    copyright_risk TEXT DEFAULT 'medium',
                    license_policy TEXT,
                    last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Migrate existing tables: add new columns if they don't exist
            self._add_column_if_missing(cursor, "episodes", "license_type", "TEXT DEFAULT 'youtube'")
            self._add_column_if_missing(cursor, "episodes", "copyright_risk", "TEXT DEFAULT 'medium'")
            
            conn.commit()
            logger.info("Database initialized (v6 schema).")

    def _add_column_if_missing(self, cursor, table: str, column: str, col_type: str):
        """Safely adds a column to an existing table if it doesn't exist."""
        try:
            cursor.execute(f"SELECT {column} FROM {table} LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            logger.info(f"Added column '{column}' to '{table}'")

    def is_episode_processed(self, video_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM episodes WHERE video_id = ?", (video_id,))
            return cursor.fetchone() is not None

    def log_episode(self, video_id: str, podcast_name: str, title: str,
                    license_type: str = "youtube", copyright_risk: str = "medium"):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO episodes (video_id, podcast_name, title, license_type, copyright_risk) VALUES (?, ?, ?, ?, ?)",
                (video_id, podcast_name, title, license_type, copyright_risk)
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

    def save_channel_info(self, channel_id: str, name: str, subscriber_count: int = 0,
                          total_videos: int = 0, country: str = None,
                          copyright_risk: str = "medium", license_policy: str = None):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO channels 
                (channel_id, name, subscriber_count, total_videos, country, copyright_risk, license_policy, last_checked)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (channel_id, name, subscriber_count, total_videos, country, copyright_risk, license_policy))
            conn.commit()

    def get_channel_info(self, channel_id: str) -> Optional[dict]:
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM channels WHERE channel_id = ?", (channel_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

db_manager = DatabaseManager()
