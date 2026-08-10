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
from fastapi import FastAPI, Request, Header
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from pymongo import MongoClient
from typing import Optional

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
    name = req.name.strip()
    email = req.email.strip()
    message = req.message.strip()

    if not name or not email or not message:
        return {"success": False, "error": "Please fill in all fields."}

    # Server-side length limits — the frontend has a maxlength too, but that
    # can be bypassed by anyone calling this endpoint directly (e.g. curl),
    # so the real limit has to be enforced here.
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


ADMIN_KEY = os.getenv("ADMIN_KEY")  # set this in your environment — no default, so it fails closed


@app.get("/api/leads")
def api_leads(x_admin_key: Optional[str] = Header(None)):
    """
    Read-back endpoint to verify submissions arrived. Protected by a simple
    shared-secret header, since this returns every visitor's name, email,
    and message — without this check, anyone who found the URL could read
    everyone's submitted data.

    Usage: curl -H "X-Admin-Key: <your key>" https://.../api/leads
    """
    if not ADMIN_KEY or x_admin_key != ADMIN_KEY:
        return JSONResponse(status_code=401, content={"success": False, "error": "Unauthorized"})

    docs = list(leads.find({}, {"_id": 0}).sort("submitted_at", -1))
    return {"count": len(docs), "leads": docs}
