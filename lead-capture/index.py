"""
Lead Capture — Standalone Contact Form (FastAPI + Jinja2 + MongoDB)
=====================================================================
A minimal, self-contained "Make It Do Something" feature: one working
contact form that saves every real submission into MongoDB.

    GET  /              -> renders the contact page (templates/contact.html)
    POST /api/contact    -> saves {name, email, message} into MongoDB

Setup:
    pip install fastapi uvicorn jinja2 pymongo python-dotenv --break-system-packages

Put your keys in a .env file:
    MONGODB_URI=mongodb+srv://.....   (same cluster you already use elsewhere is fine)

Run:
    uvicorn index:app --reload
    Then open: http://127.0.0.1:8000
"""

import os
import datetime
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from pymongo import MongoClient

load_dotenv()

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


@app.exception_handler(Exception)
async def all_exceptions_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("contact.html", {"request": request})


@app.post("/api/contact")
def api_contact(req: ContactRequest):
    """Saves a real visitor submission into MongoDB — this is the whole feature."""
    if not req.name.strip() or not req.email.strip() or not req.message.strip():
        return {"success": False, "error": "Please fill in all fields."}

    leads.insert_one({
        "name": req.name.strip(),
        "email": req.email.strip(),
        "message": req.message.strip(),
        "submitted_at": datetime.datetime.utcnow(),
    })
    return {"success": True}


@app.get("/api/leads")
def api_leads():
    """Simple read-back endpoint so you can verify submissions arrived —
    this is what you'll check to prove a real submission reached you."""
    docs = list(leads.find({}, {"_id": 0}).sort("submitted_at", -1))
    return {"count": len(docs), "leads": docs}
