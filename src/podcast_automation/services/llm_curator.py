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

    def find_best_highlight(self, transcript_segments: List[Dict], video_type: str = "short") -> Optional[Highlight]:
        # Limit transcript for analysis
        text_buffer = ""
        for seg in transcript_segments:
            if seg['start'] > settings.MAX_TRANSCRIPT_SECONDS:
                break
            text_buffer += f"[{seg['start']:.1f}s - {seg['end']:.1f}s] {seg['text']}\n"
            
        if video_type == "long":
            prompt = f"""
You are an elite podcast producer and YouTube content curator.
Your task is to analyze the following podcast transcript and extract the absolute BEST, highly engaging long-form highlight.

CRITICAL CLIP REQUIREMENTS:
1. Length: The clip MUST be between 300 and 600 seconds long (5 to 10 minutes).
2. The Hook (0-15s): The clip MUST start at an interesting topic change, a profound question, or a high-energy moment.
3. The Body: The clip must contain a deep dive into a single compelling topic, story, or debate.
4. The Payoff: The clip MUST end on a natural conclusion or a complete thought. Do NOT cut off mid-sentence.
5. Context: The clip must make sense entirely on its own without needing the rest of the podcast.

Transcript:
{text_buffer}

Return ONLY a valid JSON object with the following keys. Do NOT wrap it in markdown block quotes.
{{
  "start_time": float, // Exact start timestamp from transcript (e.g. 112.4)
  "end_time": float,   // Exact end timestamp from transcript (e.g. 455.1)
  "title": "A highly clickable YouTube video title (max 60 chars)",
  "reason": "Brief explanation of why this segment is engaging for a 5-10 minute video",
  "hashtags": ["list", "of", "4", "tags"],
  "b_roll_keyword": "A single, highly specific noun for a background thumbnail/b-roll (e.g., 'money', 'space')"
}}
"""
        else:
            prompt = f"""
You are an elite TikTok and YouTube Shorts viral content curator.
Your task is to analyze the following podcast transcript and extract the absolute BEST, most engaging clip.

CRITICAL CLIP REQUIREMENTS:
1. Length: The clip MUST be between 25 and 55 seconds long.
2. The Hook (0-3s): The clip MUST start with an attention-grabbing statement, controversial opinion, or high-energy moment. Do NOT start with boring filler (e.g., "Yeah so...", "I mean...").
3. The Body: The clip must tell a compelling micro-story, drop a valuable insight, or be extremely funny/entertaining.
4. The Payoff: The clip MUST end on a strong note (a punchline, a profound realization, or a complete thought). Do NOT cut off mid-sentence.
5. Context: The clip must make sense entirely on its own without needing the rest of the podcast.

Transcript:
{text_buffer}

Return ONLY a valid JSON object with the following keys. Do NOT wrap it in markdown block quotes.
{{
  "start_time": float, // Exact start timestamp from transcript (e.g. 112.4)
  "end_time": float,   // Exact end timestamp from transcript (e.g. 155.1)
  "title": "A highly clickable, high-retention YouTube Short title (max 50 chars)",
  "reason": "Brief explanation of why this hook and payoff will retain viewers",
  "hashtags": ["list", "of", "4", "tags"],
  "b_roll_keyword": "A single, highly specific noun for a background b-roll image (e.g., 'money', 'robot', 'brain')"
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
