"""
Lead Capture — Standalone Contact Form (FastAPI + Jinja2 + MongoDB)
=====================================================================
Original feature (unchanged):
    GET  /              -> renders the contact page (templates/contact.html)
    POST /api/contact    -> saves {name, email, message} into MongoDB

New this week (Week 7 — LLM behind the API):
    POST /api/triage     -> classifies a message's category/urgency/team
                             using an LLM, returns clean validated JSON

Setup:
    pip install fastapi uvicorn jinja2 pymongo python-dotenv openai pydantic --break-system-packages

Put your keys in a .env file:
    MONGODB_URI=mongodb+srv://.....
    LLM_BASE_URL=https://openrouter.ai/api/v1      (or http://localhost:11434/v1/ for Ollama)
    LLM_API_KEY=sk-...                              (or the literal string "ollama")
    LLM_MODEL=openrouter/free                       (or gemma3:1b)
    LLM_STUB=1                                      (1 = no real model calls, for local dev)
    LLM_ENABLED=true                                (false = kill switch, always returns fallback)
    ADMIN_KEY=some-secret-you-pick

Run:
    uvicorn index:app --reload
    Then open: http://127.0.0.1:8000
"""
import os
import datetime
import logging
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Header
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, ValidationError
from pymongo import MongoClient
from typing import Optional

from openai import APITimeoutError

from llm.client import classify_message, PROMPT_VERSION
from llm.schema import TriageResult

load_dotenv()
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Lead Capture — Contact Form")
templates = Jinja2Templates(directory="templates")

# ---------------------------------------------------------------------------
# MongoDB setup — a dedicated database ("lead_capture") so this never
# touches any collection used by another project, even if it shares the
# same cluster.
# ---------------------------------------------------------------------------
MONGO_URI = os.getenv("MONGODB_URI")
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["lead_capture"]
leads = db["leads"]


def init_db():
    leads.create_index("submitted_at")


init_db()


class ContactRequest(BaseModel):
    name: str
    email: str
    message: str


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # FastAPI's default is 422 for a Pydantic validation failure. The
    # assignment wants a 400 that names the offending field, so we translate
    # it here rather than letting the SDK default leak through.
    first = exc.errors()[0]
    field = ".".join(str(p) for p in first["loc"] if p != "body") or "body"
    return JSONResponse(
        status_code=400,
        content={"success": False, "error": f"invalid value for field '{field}': {first['msg']}"},
    )


@app.exception_handler(Exception)
async def all_exceptions_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("contact.html", {"request": request})


@app.post("/api/contact")
def api_contact(req: ContactRequest):
    """Saves a real visitor submission into MongoDB — this is the original feature."""
    name = req.name.strip()
    email = req.email.strip()
    message = req.message.strip()

    if not name or not email or not message:
        return {"success": False, "error": "Please fill in all fields."}

    if len(name) > 200:
        return {"success": False, "error": "Name is too long (max 200 characters)."}
    if len(message) > 1000:
        return {"success": False, "error": "Message is too long (max 1000 characters)."}

    leads.insert_one({
        "name": name,
        "email": email,
        "message": message,
        "submitted_at": datetime.datetime.utcnow(),
    })
    return {"success": True}


ADMIN_KEY = os.getenv("ADMIN_KEY")  # no default, so it fails closed


@app.get("/api/leads")
def api_leads(x_admin_key: Optional[str] = Header(None)):
    """Read-back endpoint, protected by a shared-secret header."""
    if not ADMIN_KEY or x_admin_key != ADMIN_KEY:
        return JSONResponse(status_code=401, content={"success": False, "error": "Unauthorized"})

    docs = list(leads.find({}, {"_id": 0}).sort("submitted_at", -1))
    return {"count": len(docs), "leads": docs}


# ---------------------------------------------------------------------------
# NEW — Week 7: LLM behind an API
# POST /api/triage — classify a message's category, urgency and target team.
# One request in, one validated JSON answer out. No conversation, no memory.
# ---------------------------------------------------------------------------

class TriageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


# Stub mode: LLM_STUB=1 skips the model entirely — used while developing so
# restarting the server twenty times costs zero model calls.
STUB_RESULT = {
    "category": "support",
    "urgency": "normal",
    "suggested_team": "support",
    "confidence": 0.42,
    "reason": "Stub mode response — no model was called.",
}


@app.post("/api/triage")
def api_triage(req: TriageRequest):
    message = req.message.strip()
    if not message:
        return JSONResponse(status_code=400, content={"success": False, "error": "field 'message' is required"})
    if len(message) > 1000:
        return JSONResponse(status_code=400, content={"success": False, "error": "field 'message' exceeds 1000 characters"})

    # Kill switch — flip LLM_ENABLED=false to disable the model call entirely
    # without a deploy (provider outage, cost spike, bad output — any reason).
    if os.getenv("LLM_ENABLED", "true").lower() == "false":
        return {
            "success": True,
            "source": "fallback",
            "result": {
                "category": "other",
                "urgency": "normal",
                "suggested_team": "general",
                "confidence": 0.0,
                "reason": "LLM disabled — routed to general queue for manual triage.",
            },
        }

    # Stub mode — no model call, for local dev / testing the contract.
    if os.getenv("LLM_STUB") == "1":
        return {"success": True, "source": "stub", "result": STUB_RESULT}

    try:
        result: TriageResult = classify_message(message)
        return {"success": True, "source": "model", "prompt_version": PROMPT_VERSION, "result": result.model_dump()}
    except APITimeoutError:
        return JSONResponse(
            status_code=504,
            content={"success": False, "error": "The classification model timed out. Please try again."},
        )
    except ValueError as e:
        return JSONResponse(
            status_code=422,
            content={"success": False, "error": f"Could not produce a valid classification: {e}"},
        )
