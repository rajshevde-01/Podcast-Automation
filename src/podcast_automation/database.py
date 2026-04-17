import sqlite3
from typing import Optional, List, Dict
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
            # Table for tracking generated shorts (extended with analytics columns)
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
                    viral_score REAL DEFAULT 0,
                    views INTEGER DEFAULT 0,
                    likes INTEGER DEFAULT 0,
                    comments INTEGER DEFAULT 0,
                    analytics_fetched_at TIMESTAMP,
                    FOREIGN KEY (episode_id) REFERENCES episodes(video_id)
                )
            """)
            # Table for resumable pipeline state
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pipeline_states (
                    run_id TEXT PRIMARY KEY,
                    stage TEXT NOT NULL,
                    episode_id TEXT,
                    podcast_name TEXT,
                    audio_path TEXT,
                    segment_path TEXT,
                    final_video_path TEXT,
                    thumbnail_path TEXT,
                    highlight_json TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

            # Migrate existing shorts table: add columns if they don't exist
            for col, col_def in [
                ("viral_score", "REAL DEFAULT 0"),
                ("views", "INTEGER DEFAULT 0"),
                ("likes", "INTEGER DEFAULT 0"),
                ("comments", "INTEGER DEFAULT 0"),
                ("analytics_fetched_at", "TIMESTAMP"),
            ]:
                try:
                    cursor.execute(f"ALTER TABLE shorts ADD COLUMN {col} {col_def}")
                    conn.commit()
                except sqlite3.OperationalError:
                    pass  # Column already exists

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

    def log_short(
        self,
        episode_id: str,
        start_time: float,
        end_time: float,
        title: str,
        viral_score: float = 0.0,
    ) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO shorts (episode_id, start_time, end_time, title, viral_score) "
                "VALUES (?, ?, ?, ?, ?)",
                (episode_id, start_time, end_time, title, viral_score)
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

    # ------------------------------------------------------------------
    # Analytics helpers
    # ------------------------------------------------------------------

    def update_short_analytics(self, short_id: int, views: int, likes: int, comments: int):
        """Store YouTube performance metrics for a published short."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE shorts
                   SET views = ?, likes = ?, comments = ?,
                       analytics_fetched_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (views, likes, comments, short_id)
            )
            conn.commit()

    def get_shorts_pending_analytics(self, delay_hours: int = 24) -> List[dict]:
        """Return uploaded shorts whose analytics have not been fetched yet (or are stale)."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """SELECT * FROM shorts
                   WHERE is_uploaded = 1
                     AND video_url IS NOT NULL
                     AND (
                       analytics_fetched_at IS NULL
                       OR (
                         CAST((julianday('now') - julianday(analytics_fetched_at)) * 24 AS INTEGER) >= ?
                         AND views < 10000
                       )
                     )
                     AND CAST((julianday('now') - julianday(created_at)) * 24 AS INTEGER) >= ?
                   ORDER BY created_at DESC
                   LIMIT 20""",
                (delay_hours, delay_hours)
            )
            return [dict(r) for r in cursor.fetchall()]

    def get_top_performing_clips(self, limit: int = 5) -> List[dict]:
        """Return the top-performing clips for the LLM feedback loop."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """SELECT s.title, s.views, s.likes, s.viral_score,
                          e.podcast_name, s.start_time, s.end_time
                   FROM shorts s
                   LEFT JOIN episodes e ON s.episode_id = e.video_id
                   WHERE s.is_uploaded = 1 AND s.views > 0
                   ORDER BY s.views DESC
                   LIMIT ?""",
                (limit,)
            )
            return [dict(r) for r in cursor.fetchall()]

    # ------------------------------------------------------------------
    # Resumable pipeline state
    # ------------------------------------------------------------------

    def save_pipeline_state(self, run_id: str, stage: str, **kwargs):
        """Upsert the pipeline state for a given run_id."""
        fields = ["run_id", "stage"] + list(kwargs.keys())
        placeholders = ", ".join(["?"] * len(fields))
        updates = ", ".join(
            f"{k} = excluded.{k}" for k in ["stage"] + list(kwargs.keys())
        ) + ", updated_at = CURRENT_TIMESTAMP"
        values = [run_id, stage] + list(kwargs.values())

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"""INSERT INTO pipeline_states ({', '.join(fields)})
                    VALUES ({placeholders})
                    ON CONFLICT(run_id) DO UPDATE SET {updates}""",
                values
            )
            conn.commit()

    def get_pipeline_state(self, run_id: str) -> Optional[dict]:
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM pipeline_states WHERE run_id = ?", (run_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def delete_pipeline_state(self, run_id: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM pipeline_states WHERE run_id = ?", (run_id,)
            )
            conn.commit()

db_manager = DatabaseManager()
