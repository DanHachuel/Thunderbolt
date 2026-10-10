"""Pydantic schemas for Remotion blueprint LLM output validation.

One model per Remotion format. The output_schema in the format file
(packages/remotion/schemas/*.schema.json) is the documented source of truth;
these Pydantic models are the runtime barrier. If a format is updated, the
corresponding schema must be updated too.

0.9.76: as chaves passam a ser os format_ids novos (quiz, social_reel,
top_10, would_you_rather, inspirational) — os modelos Pydantic mantêm-se.
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
    "inspirational": InspirationalLongFormOutput,
    "quiz": QuizVideosOutput,
    "social_reel": SocialMediaReelsOutput,
    "top_10": Top10VideosOutput,
    "would_you_rather": WouldYouRatherOutput,
}

__all__ = ["SCHEMAS", "InspirationalLongFormOutput", "QuizVideosOutput", "SocialMediaReelsOutput", "Top10VideosOutput", "WouldYouRatherOutput"]
