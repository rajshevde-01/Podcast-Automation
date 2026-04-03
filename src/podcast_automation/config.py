import os
from pathlib import Path
from typing import List, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # API Keys
    GROQ_API_KEY: Optional[str] = None
    YOUTUBE_CLIENT_ID: Optional[str] = None
    YOUTUBE_CLIENT_SECRET: Optional[str] = None
    YOUTUBE_REFRESH_TOKEN: Optional[str] = None
    DISCORD_WEBHOOK_URL: Optional[str] = None

    # Paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    DATA_DIR: Path = BASE_DIR / "data"
    OUTPUT_DIR: Path = BASE_DIR / "output"
    ASSETS_DIR: Path = BASE_DIR / "assets"
    
    DB_PATH: str = str(BASE_DIR / "podcast_automation.db")
    COOKIES_FILE: str = str(BASE_DIR / "cookies.txt")
    PODCASTS_LIST_FILE: str = str(BASE_DIR / "podcasts_list.json")
    
    # Pipeline Settings
    TARGET_SHORT_DURATION: int = 60
    MIN_EPISODE_DURATION: int = 600 # 10 mins
    MAX_TRANSCRIPT_SECONDS: int = 1200 # 20 mins for analysis
    
    # Video Settings
    VIDEO_WIDTH: int = 1080
    VIDEO_HEIGHT: int = 1920
    FPS: int = 30
    
    # Whisper Settings
    WHISPER_MODEL: str = "base"
    WHISPER_DEVICE: str = "cpu"
    WHISPER_COMPUTE_TYPE: str = "int8"
    
    # LLM Settings
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    def __init__(self, **values):
        super().__init__(**values)
        # Ensure directories exist
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self.ASSETS_DIR.mkdir(parents=True, exist_ok=True)

settings = Settings()
