import os
import json
from typing import List, Dict, Optional
from groq import Groq
from ..config import settings
from ..models import Highlight
from ..utils.retry import with_retry
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

    def _call_llm(self, messages: List[Dict], temperature: float = 0.7) -> Optional[str]:
        """Thin wrapper around the Groq chat API with retry."""
        @with_retry(max_attempts=3, base_delay=2.0)
        def _call():
            completion = self.client.chat.completions.create(
                messages=messages,
                model=settings.GROQ_MODEL,
                temperature=temperature,
                response_format={"type": "json_object"},
            )
            return completion.choices[0].message.content
        try:
            return _call()
        except Exception as e:
            logger.error(f"Groq API call failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Guest / topic detection
    # ------------------------------------------------------------------

    def detect_guest_and_topic(self, transcript_segments: List[Dict]) -> Dict:
        """
        Use the LLM to extract the guest name and main topic from the transcript.
        Returns a dict with keys 'guest_name' and 'topic'.
        """
        # Use only the first ~3 minutes for speed
        text_sample = ""
        for seg in transcript_segments:
            if seg["start"] > 180:
                break
            text_sample += seg["text"] + " "

        prompt = f"""
Analyze this podcast transcript opening and extract:
1. The guest's name (if this is an interview format; otherwise null)
2. The main topic being discussed

Transcript (first 3 minutes):
{text_sample[:2000]}

Return ONLY a valid JSON object:
{{
  "guest_name": "Name or null if not an interview",
  "topic": "One short phrase describing the main topic (e.g. 'AI startups', 'mental health', 'crypto')"
}}
"""
        response = self._call_llm([
            {"role": "system", "content": "You are a JSON-only response bot."},
            {"role": "user", "content": prompt},
        ], temperature=0.3)

        if response:
            try:
                data = json.loads(response)
                return {
                    "guest_name": data.get("guest_name") or None,
                    "topic": data.get("topic") or None,
                }
            except Exception:
                pass
        return {"guest_name": None, "topic": None}

    # ------------------------------------------------------------------
    # Multi-highlight extraction
    # ------------------------------------------------------------------

    def find_best_highlights(
        self,
        transcript_segments: List[Dict],
        top_performing_clips: Optional[List[Dict]] = None,
        n: int = settings.MAX_HIGHLIGHTS_PER_RUN,
    ) -> List[Highlight]:
        """
        Extract the top *n* viral highlights from *transcript_segments*.

        If *top_performing_clips* is provided (from the DB feedback loop) they
        are injected into the prompt so the LLM can learn what format/style
        performs best on this channel.

        Returns a list sorted by viral_score descending.
        """
        text_buffer = ""
        for seg in transcript_segments:
            if seg["start"] > settings.MAX_TRANSCRIPT_SECONDS:
                break
            text_buffer += f"[{seg['start']:.1f}s - {seg['end']:.1f}s] {seg['text']}\n"

        # Build optional performance context block
        perf_block = ""
        if top_performing_clips:
            perf_block = "\n\nTop-performing past clips on this channel (learn from these styles):\n"
            for clip in top_performing_clips:
                perf_block += (
                    f"  - \"{clip.get('title')}\" — {clip.get('views', 0):,} views, "
                    f"{clip.get('likes', 0):,} likes\n"
                )

        prompt = f"""
You are an expert viral content curator for YouTube Shorts and TikTok.
Analyze the transcript below and find the {n} MOST viral, engaging or controversial segments.
Each segment must:
- Be between 45s and 60s long
- Have a strong hook within the first 3 seconds
- Contain a single clear insight, story, or emotional peak
{perf_block}

Transcript:
{text_buffer}

Return ONLY a valid JSON object with key "highlights" containing an array of {n} objects:
{{
  "highlights": [
    {{
      "start_time": float,
      "end_time": float,
      "title": "Short catchy title (max 8 words)",
      "reason": "Why this will go viral",
      "viral_score": float (1-10),
      "hashtags": ["list", "of", "5", "tags"],
      "b_roll_keyword": "single noun topic for visual aid",
      "guest_name": "Guest name if applicable or null",
      "topic": "One-phrase topic"
    }}
  ]
}}
Sort the array by viral_score descending.
"""
        logger.info(f"Calling Groq LLM for top-{n} highlight extraction...")
        response = self._call_llm([
            {"role": "system", "content": "You are a JSON-only response bot."},
            {"role": "user", "content": prompt},
        ])

        if not response:
            return []

        try:
            data = json.loads(response)
            raw_highlights = data.get("highlights", [])
            if not isinstance(raw_highlights, list):
                raw_highlights = [data]  # fallback: single-object response

            highlights = []
            for item in raw_highlights[:n]:
                try:
                    h = Highlight(
                        start_time=float(item.get("start_time", 0)),
                        end_time=float(item.get("end_time", 0)),
                        title=item.get("title", "Untitled"),
                        reason=item.get("reason", ""),
                        hashtags=item.get("hashtags", []),
                        b_roll_keyword=item.get("b_roll_keyword"),
                        viral_score=float(item.get("viral_score", 5.0)),
                        guest_name=item.get("guest_name") or None,
                        topic=item.get("topic") or None,
                    )
                    highlights.append(h)
                except Exception as parse_err:
                    logger.warning(f"Skipping malformed highlight: {parse_err}")

            highlights.sort(key=lambda x: x.viral_score, reverse=True)
            logger.info(
                f"✅ LLM found {len(highlights)} highlights. "
                f"Best: '{highlights[0].title}' (score={highlights[0].viral_score})"
                if highlights else "✅ LLM returned 0 highlights."
            )
            return highlights

        except Exception as e:
            logger.error(f"Highlight parsing error: {e}")
            return []

    # ------------------------------------------------------------------
    # Legacy single-highlight helper (backwards-compat)
    # ------------------------------------------------------------------

    def find_best_highlight(
        self, transcript_segments: List[Dict]
    ) -> Optional[Highlight]:
        highlights = self.find_best_highlights(transcript_segments, n=1)
        return highlights[0] if highlights else None

curator = CuratorService()
