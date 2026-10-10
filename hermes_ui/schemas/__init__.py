"""Pydantic schemas for Remotion blueprint LLM output validation.

One model per Remotion blueprint composition. The output_schema in the
blueprint JSON is the documented source of truth; these Pydantic models are
the runtime barrier. If a blueprint is updated, the corresponding schema must
be updated too.

0.9.79: um blueprint é um blueprint — as chaves são os composition_id dos
próprios blueprints (Quiz, SocialReel, Top10, WouldYouRather,
InspirationalVideo). Nota: o {{difficulty}} é um placeholder do PROMPT,
resolvido no pipeline antes da chamada ao LLM; não faz parte do output.
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
    "InspirationalVideo": InspirationalLongFormOutput,
    "Quiz": QuizVideosOutput,
    "SocialReel": SocialMediaReelsOutput,
    "Top10": Top10VideosOutput,
    "WouldYouRather": WouldYouRatherOutput,
}

__all__ = ["SCHEMAS", "InspirationalLongFormOutput", "QuizVideosOutput", "SocialMediaReelsOutput", "Top10VideosOutput", "WouldYouRatherOutput"]
