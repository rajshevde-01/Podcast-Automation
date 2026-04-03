import os
import json
from typing import List, Dict, Optional
from groq import Groq
from ..config import settings
from ..models import Highlight
from loguru import logger

class CuratorService:
    def __init__(self, api_key: str = settings.GROQ_API_KEY):
        self.api_key = api_key
        self._client = None

    @property
    def client(self):
        if not self.api_key:
            raise ValueError("GROQ_API_KEY is not set.")
        if self._client is None:
            self._client = Groq(api_key=self.api_key)
        return self._client

    def find_best_highlight(self, transcript_segments: List[Dict]) -> Optional[Highlight]:
        # Limit transcript for analysis
        text_buffer = ""
        for seg in transcript_segments:
            if seg['start'] > settings.MAX_TRANSCRIPT_SECONDS:
                break
            text_buffer += f"[{seg['start']:.1f}s - {seg['end']:.1f}s] {seg['text']}\n"
            
        prompt = f"""
You are an expert viral content curator for YouTube Shorts and TikTok.
Analyze the following transcript and find the single MOST viral, engaging, or controversial segment between 45s and 60s.
The segment must have a strong hook within the first 3 seconds.

Transcript:
{text_buffer}

Return ONLY a valid JSON object with the following keys:
{{
  "start_time": float,
  "end_time": float,
  "title": "Short catchy title",
  "reason": "Why this will go viral",
  "hashtags": ["list", "of", "5", "tags"],
  "b_roll_keyword": "single noun topic for visual aid"
}}
"""
        logger.info("Calling Groq LLM for highlight selection...")
        try:
            completion = self.client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "You are a JSON-only response bot."},
                    {"role": "user", "content": prompt}
                ],
                model=settings.GROQ_MODEL,
                temperature=0.7,
                response_format={"type": "json_object"}
            )
            
            response_text = completion.choices[0].message.content
            data = json.loads(response_text)
            logger.info(f"✅ LLM Found Highlight: {data.get('title')}")
            return Highlight(**data)
            
        except Exception as e:
            logger.error(f"Groq API Error: {e}")
            return None

curator = CuratorService()
