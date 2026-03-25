import os
import json
import re
import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from models import ChatRequest, ChatResponse, Correction, Message
from prompt import SYSTEM_PROMPT

load_dotenv()

app = FastAPI(title="Gen Z English Tutor API", version="1.0.0")

# Allow your frontend (running on localhost:3000 or 5173) to talk to this backend
app.add_middleware(
    CORSMiddleware,
    # allow_origins=[
    #     "http://localhost:3000",
    #     "http://localhost:5173",
    #     "http://127.0.0.1:3000",
    #     "http://127.0.0.1:5173",
    # ],
    allow_origins=["*"],  # Allow all origins for development; restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def extract_json_from_text(text: str) -> str:
    # allow simple JSON objects even if model wraps them in text or markdown fences
    if not text:
        return ""

    cleaned = text.strip()
    cleaned = cleaned.replace("```json", "").replace("```", "").strip()

    if (cleaned.startswith("'") and cleaned.endswith("'")) or (cleaned.startswith('"') and cleaned.endswith('"')):
        cleaned = cleaned[1:-1].strip()

    # direct JSON path first
    if cleaned.startswith("{") and cleaned.endswith("}"):
        return cleaned

    # fallback: extract substring between first { and last }
    first = cleaned.find("{")
    last = cleaned.rfind("}")
    if first != -1 and last != -1 and first < last:
        return cleaned[first : last + 1]

    return cleaned


def normalize_json_like(text: str) -> str:
    # Normalize common model-output JSON mistakes (missing commas, trailing commas)
    normalized = text

    # remove trailing commas before object/array closes
    normalized = re.sub(r",\s*(?=[}\]])", "", normalized)

    # ensure there's a comma between ended object/array and next key
    normalized = re.sub(r"(?<=[}\]])\s*(?=\")", ", ", normalized)

    return normalized


@app.get("/")
def root():
    return {"status": "ok", "message": "Gen Z Tutor API is running 🔥"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # Build conversation history for Claude
    # We only pass the raw user text in history — the assistant responses
    # are stored as the full JSON string (that's what Claude actually returned)
    messages = []
    for msg in request.history:
        messages.append({"role": msg.role, "content": msg.content})

    # Add the new user message
    messages.append({"role": "user", "content": request.message})

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
    except anthropic.AuthenticationError:
        raise HTTPException(
            status_code=401,
            detail="Invalid Anthropic API key. Check your .env file.",
        )
    except anthropic.APIError as e:
        raise HTTPException(status_code=502, detail=f"Claude API error: {str(e)}")

    raw_text = response.content[0].text.strip()
    candidate_json = extract_json_from_text(raw_text)

    # Claude should always return JSON — parse it
    try:
        data = json.loads(candidate_json)
    except json.JSONDecodeError as exc:
        # second chance with minor normalization for common output errors
        candidate_fixed = normalize_json_like(candidate_json)
        try:
            data = json.loads(candidate_fixed)
        except json.JSONDecodeError as exc2:
            raise HTTPException(
                status_code=500,
                detail=(
                    "Could not parse model response as JSON after normalization. "
                    f"Model output: {raw_text[:1000]!r}. "
                    f"Candidate JSON: {candidate_json[:1000]!r}. "
                    f"Fixed candidate: {candidate_fixed[:1000]!r}. "
                    f"Error1: {str(exc)}. Error2: {str(exc2)}"
                ),
            )

    corrections = [
        Correction(
            original=c.get("original", ""),
            corrected=c.get("corrected", ""),
            explanation=c.get("explanation", ""),
        )
        for c in data.get("corrections", [])
    ]

    return ChatResponse(
        reply=data.get("reply", ""),
        corrections=corrections,
        no_errors=data.get("no_errors", len(corrections) == 0),
        raw_message=request.message,
    )