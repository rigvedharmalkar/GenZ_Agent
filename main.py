import os
import json
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
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


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

    # Claude should always return JSON — parse it
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        # Fallback: if Claude slipped up and wrapped in markdown fences
        cleaned = raw_text.replace("```json", "").replace("```", "").strip()
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=500,
                detail="Could not parse model response as JSON. Try again.",
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