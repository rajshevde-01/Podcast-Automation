import re
import random
from typing import List, Dict, Optional
from loguru import logger
from ..models import Highlight

class MetadataBuilder:
    # ── Category ID Mapping ──
    # Official YouTube category IDs
    CATEGORY_PEOPLE_AND_BLOGS = "22"
    CATEGORY_EDUCATION = "27"
    CATEGORY_COMEDY = "23"
    CATEGORY_ENTERTAINMENT = "24"
    CATEGORY_SCIENCE_TECH = "28"
    CATEGORY_NEWS_POLITICS = "25"

    @classmethod
    def get_category_id(cls, theme: Optional[str]) -> str:
        """
        Dynamically map the podcast theme to the best YouTube category ID.
        """
        if not theme:
            return cls.CATEGORY_PEOPLE_AND_BLOGS

        theme_lower = theme.lower()
        
        # Science & Tech
        if any(term in theme_lower for term in ["science", "neuroscience", "physics", "tech", "technology", "coding", "software"]):
            return cls.CATEGORY_SCIENCE_TECH
        
        # Comedy
        if any(term in theme_lower for term in ["comedy", "humor", "unfiltered", "roast"]):
            return cls.CATEGORY_COMEDY
        
        # Education / Intellectual / Business
        if any(term in theme_lower for term in ["education", "psychology", "philosophy", "self-improvement", "motivation", "business", "startups", "finance", "investing", "economy", "entrepreneurship", "career"]):
            return cls.CATEGORY_EDUCATION
        
        # Entertainment / Lifestyle
        if any(term in theme_lower for term in ["entertainment", "pop culture", "culture", "drama", "tiktok", "lifestyle", "influencers", "celebrities"]):
            return cls.CATEGORY_ENTERTAINMENT
            
        # News & Politics
        if any(term in theme_lower for term in ["politics", "current events", "debates", "military", "intelligence"]):
            return cls.CATEGORY_NEWS_POLITICS

        return cls.CATEGORY_PEOPLE_AND_BLOGS

    # ── Hooks & Visual Title Curators ──
    HOOK_EMOJIS = ["🤯", "🚨", "🔥", "💡", "🧠", "🤫", "⚠️", "👀", "💎", "🏆", "⚡", "🌟"]

    @classmethod
    def curate_title(cls, raw_title: str) -> str:
        """
        Takes a plain title and transforms it into a clicky, high-retention hook title.
        Ensures proper spacing, styling, and emoji prefixing.
        """
        # Clean up any trailing / leading hashes
        clean_title = raw_title.strip().rstrip("#shorts").rstrip("#short").strip()
        
        # Strip preexisting emojis at start if any to avoid duplicates
        clean_title = re.sub(r"^[^\w\s]+", "", clean_title).strip()
        
        # Choose a cool high-performance emoji
        prefix_emoji = random.choice(cls.HOOK_EMOJIS)
        
        # Format the title with the hook emoji and standard casing
        formatted = f"{prefix_emoji} {clean_title}"
        
        # Truncate to maximum length of 85 characters for Shorts safety in mobile feed
        if len(formatted) > 85:
            formatted = formatted[:82] + "..."
            
        return formatted

    # ── Premium Structured Descriptions ──
    @classmethod
    def generate_description(
        cls,
        title: str,
        podcast_name: str,
        episode_title: str,
        guest_name: Optional[str] = None,
        topic: Optional[str] = None,
        hashtags: Optional[List[str]] = None,
        custom_teaser: Optional[str] = None
    ) -> str:
        """
        Generates a premium, structured, high-conversion description for YouTube.
        """
        # Build clean guest info
        guest_line = f"👤 Featuring: {guest_name}\n" if guest_name else ""
        topic_line = f"🎯 Theme: {topic}\n" if topic else ""
        
        # Hook/teaser description paragraph
        teaser_paragraph = custom_teaser or "Check out this high-value highlight from the episode! Learn key concepts and insights shared by the host and guests."
        
        # Standardize hashtags
        tags_list = hashtags or ["podcast", "shorts", "wisdom"]
        # Make sure they are clean (no spaces, no #)
        clean_tags = []
        for tag in tags_list:
            cleaned = re.sub(r"[^a-zA-Z0-9]", "", tag)
            if cleaned:
                clean_tags.append(f"#{cleaned.lower()}")
                
        # Append defaults if list is short
        for fallback in ["shorts", "podcastclips", "dailyinsights"]:
            if len(clean_tags) < 5 and f"#{fallback}" not in clean_tags:
                clean_tags.append(f"#{fallback}")
                
        hashtag_line = " ".join(clean_tags)

        # Beautiful premium template
        desc = (
            f"🔥 {title}\n\n"
            f"✨ QUICK SUMMARY:\n"
            f"{teaser_paragraph}\n\n"
            f"🎙️ SHOW DETAILS:\n"
            f"🔹 Podcast: {podcast_name}\n"
            f"{guest_line}"
            f"{topic_line}"
            f"🔹 Original Video: {episode_title}\n\n"
            f"🔔 JOIN THE WISDOM BYTES COMMUNITY:\n"
            f"Subscribe to our channel for your daily dose of high-value wisdom, mindset shifts, and actionable strategies! Like, share, and comment to support the creator ecosystem.\n\n"
            f"🏷️ SEO TAGS:\n"
            f"{hashtag_line}\n"
        )
        return desc

    # ── Smart Tag Lists ──
    @classmethod
    def generate_tags(
        cls,
        podcast_name: str,
        guest_name: Optional[str] = None,
        topic: Optional[str] = None,
        hashtags: Optional[List[str]] = None
    ) -> List[str]:
        """
        Returns a list of clean tag strings optimized for search systems.
        """
        tags = ["shorts", "podcast", "podcast clips", "short clips", "highlights", "motivation"]
        
        # Podcast name variations
        if podcast_name:
            tags.append(podcast_name.lower())
            tags.append(f"{podcast_name.lower()} clips")
            
        # Guest name variations
        if guest_name:
            tags.append(guest_name.lower())
            tags.append(f"{guest_name.lower()} podcast")
            tags.append(f"{guest_name.lower()} interview")
            
        # Topic variations
        if topic:
            tags.append(topic.lower())
            if " " in topic:
                tags.extend([t.lower() for t in topic.split()])
                
        # Hashtags
        if hashtags:
            for tag in hashtags:
                clean_tag = re.sub(r"[^a-zA-Z0-9\s]", "", tag).strip().lower()
                if clean_tag and clean_tag not in tags:
                    tags.append(clean_tag)
                    
        # Max limit safety
        return tags[:20]

metadata_builder = MetadataBuilder()
