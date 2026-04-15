from typing import List, Dict
import os
from faster_whisper import WhisperModel
from ..config import settings
from loguru import logger

class TranscriptionService:
    def __init__(self, model_size: str = settings.WHISPER_MODEL, device: str = settings.WHISPER_DEVICE):
        self.model_size = model_size
        self.device = device
        self._model = None
        # Set local cache dir to avoid permission issues with system .cache
        os.environ["HF_HOME"] = str(settings.DATA_DIR / "cache")
        os.environ["XDG_CACHE_HOME"] = str(settings.DATA_DIR / "cache")

    @property
    def model(self):
        if self._model is None:
            logger.info(f"Loading Whisper model: {self.model_size}")
            self._model = WhisperModel(
                self.model_size,
                device=settings.WHISPER_DEVICE,
                compute_type=settings.WHISPER_COMPUTE_TYPE
            )
        return self._model

    def transcribe(self, audio_path: str, word_timestamps: bool = False) -> List[Dict]:
        logger.info(f"Transcribing: {audio_path}")
        segments, info = self.model.transcribe(audio_path, beam_size=5, word_timestamps=word_timestamps)
        
        logger.info(f"Detected language: {info.language} ({info.language_probability:.2f})")
        
        results = []
        for segment in segments:
            seg_dict = {
                "start": segment.start,
                "end": segment.end,
                "text": segment.text.strip()
            }
            if word_timestamps and segment.words:
                seg_dict["words"] = [
                    {"start": w.start, "end": w.end, "text": w.word.strip()}
                    for w in segment.words
                ]
            results.append(seg_dict)
            
        return results

processor = TranscriptionService()
