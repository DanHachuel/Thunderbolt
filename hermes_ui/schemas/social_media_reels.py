from __future__ import annotations

from pydantic import BaseModel, Field


class SocialReelScene(BaseModel):
    id: str = Field(..., min_length=1)
    scene_type: str = Field(..., min_length=1)
    voiceOverText: str = Field(..., min_length=5)
    imagePrompt: str = Field(..., min_length=5)
    durationInSeconds: float = Field(..., gt=0)


class SocialMediaReelsOutput(BaseModel):
    title: str = Field(..., min_length=2)
    scenes: list[SocialReelScene] = Field(..., min_length=3, max_length=5)
