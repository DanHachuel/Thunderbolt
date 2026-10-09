from __future__ import annotations

from pydantic import BaseModel, Field


class Top10IntroOutro(BaseModel):
    voiceoverText: str = Field(..., min_length=5)
    imagePrompt: str = Field(..., min_length=5)
    durationInSeconds: float = Field(..., gt=0)


class Top10RankingItem(BaseModel):
    rank: int = Field(..., ge=1, le=10)
    voiceoverText: str = Field(..., min_length=10)
    imagePrompt: str = Field(..., min_length=5)
    lowerThirdText: str = Field(..., min_length=1)
    durationInSeconds: float = Field(..., gt=0)


class Top10VideosOutput(BaseModel):
    subjectIdeas: list[str] = Field(..., min_length=5, max_length=10)
    title: str = Field(..., min_length=2)
    intro: Top10IntroOutro
    ranking: list[Top10RankingItem] = Field(..., min_length=10, max_length=10)
    outro: Top10IntroOutro
