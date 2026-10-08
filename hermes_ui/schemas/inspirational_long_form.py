from __future__ import annotations

from pydantic import BaseModel, Field


class InspirationalScene(BaseModel):
    id: str = Field(..., min_length=1)
    scene_type: str = Field(..., min_length=1)
    voiceover_text: str = Field(..., min_length=5)
    image_prompt: str = Field(..., min_length=5)
    durationInSeconds: float = Field(..., gt=0)


class InspirationalLongFormOutput(BaseModel):
    title: str = Field(..., min_length=2)
    scenes: list[InspirationalScene] = Field(..., min_length=3, max_length=10)
