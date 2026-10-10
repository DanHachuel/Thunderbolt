from __future__ import annotations

from pydantic import BaseModel, Field

# Nota (0.9.78): o {{difficulty}} do formato quiz é um placeholder do PROMPT,
# resolvido em hermes_ui/pipeline_worker.py antes da chamada ao LLM (default
# "Average" de default_values). Não faz parte do output — o JSON que o LLM
# devolve não contém difficulty e este modelo não o valida.


class QuizQuestion(BaseModel):
    question: str = Field(..., min_length=3, max_length=200)
    answer1: str = Field(..., min_length=1)
    answer2: str = Field(..., min_length=1)
    answer3: str = Field(..., min_length=1)
    answer4: str = Field(..., min_length=1)
    correct_answer: int = Field(..., ge=1, le=4)
    durationInSeconds: float = Field(..., gt=0)
    revealDelaySeconds: float = Field(..., gt=0)


class QuizVideosOutput(BaseModel):
    topic: str = Field(..., min_length=2)
    intro_voiceover: str = Field(..., min_length=10)
    like_and_subscribe_voiceover: str = Field(..., min_length=10)
    questions: list[QuizQuestion] = Field(..., min_length=5, max_length=5)
