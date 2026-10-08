"""Pydantic schemas for Remotion blueprint LLM output validation.

One model per blueprint. The output_schema in the blueprint JSON is the
documented source of truth; these Pydantic models are the runtime barrier.
If a blueprint is updated, the corresponding schema must be updated too.
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Literal

from .inspirational_long_form import InspirationalLongFormOutput
from .quiz_videos import QuizVideosOutput
from .social_media_reels import SocialMediaReelsOutput
from .top_10_videos import Top10VideosOutput
from .would_you_rather import WouldYouRatherOutput

SCHEMAS: dict[str, type[BaseModel]] = {
    "inspirational_long_form": InspirationalLongFormOutput,
    "quiz_videos": QuizVideosOutput,
    "social_media_reels": SocialMediaReelsOutput,
    "top_10_videos": Top10VideosOutput,
    "would_you_rather": WouldYouRatherOutput,
}

__all__ = ["SCHEMAS", "InspirationalLongFormOutput", "QuizVideosOutput", "SocialMediaReelsOutput", "Top10VideosOutput", "WouldYouRatherOutput"]
