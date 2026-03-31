import os
import json
from faster_whisper import WhisperModel
from groq import Groq

# Ensure API key is set
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
if not GROQ_API_KEY:
    try:
        from dotenv import load_dotenv
        load_dotenv()
        GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
    except ImportError:
        pass

def transcribe_audio(audio_path: str):
    """
    Transcribes the audio file using local faster-whisper.
    Returns a list of segments with start, end, and text.
    """
    print(f"Loading Whisper model to transcribe {audio_path}...")
    # Use base or small model for fast initial transcription
    model = WhisperModel("base", device="cpu", compute_type="int8")
    
    segments, info = model.transcribe(audio_path, beam_size=5)
    
    print(f"Detected language '{info.language}' with probability {info.language_probability}")
    
    transcript = []
    for segment in segments:
        transcript.append({
            "start": segment.start,
            "end": segment.end,
            "text": segment.text.strip()
        })
    return transcript

def find_best_highlight(transcript_segments, target_duration=60):
    """
    Sends the transcript to an LLM (Groq) to identify the most viral 45-60s chunk.
    Works by assembling the transcript into a text block with timestamps.
    """
    if not GROQ_API_KEY:
        print("WARNING: GROQ_API_KEY not set. Cannot use LLM to find highlights.")
        # Fallback: just return the first 60 seconds of speaking
        if not transcript_segments: return None
        return {
            "start_time": transcript_segments[0]["start"],
            "end_time": transcript_segments[0]["start"] + target_duration,
            "title": "Fallback Highlight",
            "reason": "No API key",
            "hashtags": ["podcast", "clips", "shorts", "viral", "trending"],
            "b_roll_keyword": "podcast"
        }
        
    client = Groq(api_key=GROQ_API_KEY)
    
    # We only send the first ~20 minutes of transcript to save tokens (or chunk it)
    # Most viral hooks are in the intro, but let's take a good chunk
    text_buffer = ""
    for seg in transcript_segments:
        if seg['end'] > 1200: # 20 mins max for MVP
            break
        text_buffer += f"[{seg['start']:.1f}s - {seg['end']:.1f}s] {seg['text']}\n"
        
    prompt = f"""
You are an expert TikTok/YouTube Shorts viral content curator.
Analyze this podcast transcript and find the single MOST viral, engaging, controversial, or mind-blowing contiguous segment that is exactly 45 to 60 seconds long.
The segment must have a strong hook at the start and leave the viewer satisfied or wanting more at the end.

Transcript excerpt:
{text_buffer}

You must return ONLY a valid JSON object with the following keys. DO NOT return markdown or explanation.
{{
  "start_time": float (exact start timestamp in seconds from the transcript),
  "end_time": float (exact end timestamp in seconds),
  "title": "A highly clickable 3-5 word title for the short",
  "reason": "A 1 sentence explanation of why this goes viral",
  "hashtags": ["list", "of", "5", "trending", "SEO tags"],
  "b_roll_keyword": "A single highly visual, generic noun representing the main topic (e.g., 'money', 'brain', 'space', 'car', 'gym')"
}}
"""
    print("Calling Groq LLM to analyze the transcript...")
    chat_completion = client.chat.completions.create(
        messages=[
            {"role": "system", "content": "You are a JSON-only bot. Output only valid JSON."},
            {"role": "user", "content": prompt}
        ],
        model="llama3-70b-8192",
        temperature=0.7,
    )
    
    response_text = chat_completion.choices[0].message.content.strip()
    
    # Clean up response if the LLM added markdown formatting
    if response_text.startswith("```json"):
        response_text = response_text[7:-3]
    elif response_text.startswith("```"):
        response_text = response_text[3:-3]
        
    try:
        data = json.loads(response_text)
        print(f"Found Highlight: '{data.get('title')}' ({data.get('start_time')}s - {data.get('end_time')}s)")
        return data
    except json.JSONDecodeError:
        print(f"Failed to parse LLM response as JSON: {response_text}")
        return None

if __name__ == "__main__":
    # Test script: Provide an m4a file in the directory to test
    test_file = "test.m4a"
    if os.path.exists(test_file):
        trans = transcribe_audio(test_file)
        highlight = find_best_highlight(trans)
        print(json.dumps(highlight, indent=2))
    else:
        print("Provide a test.m4a file in the directory to run the module directly.")
