from pydantic import BaseModel
from typing import List, Optional


class Message(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[Message] = []


class Correction(BaseModel):
    original: str
    corrected: str
    explanation: str


class ChatResponse(BaseModel):
    reply: str
    corrections: List[Correction]
    no_errors: bool
    raw_message: str  # echo back the user's original message for display