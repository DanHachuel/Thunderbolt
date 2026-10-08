from __future__ import annotations

from pydantic import BaseModel, Field


class WouldYouRatherQuestion(BaseModel):
    id: str = Field(..., min_length=1)
    option1_text: str = Field(..., min_length=1)
    option1_image_prompt: str = Field(..., min_length=5)
    option2_text: str = Field(..., min_length=1)
    option2_image_prompt: str = Field(..., min_length=5)
    option1_result: int = Field(..., ge=0, le=100)
    voiceover_text: str = Field(..., min_length=5)
    durationInSeconds: float = Field(..., gt=0)
    thinkingDelaySeconds: float = Field(..., gt=0)
    revealDurationSeconds: float = Field(..., gt=0)


class WouldYouRatherOutput(BaseModel):
    like_and_subscribe_voiceover_text: str = Field(..., min_length=10)
    or_text: str = Field(..., min_length=1)
    questions: list[WouldYouRatherQuestion] = Field(..., min_length=5, max_length=5)
