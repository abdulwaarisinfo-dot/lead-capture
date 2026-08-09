# Lead Capture — Contact Form

A minimal, standalone "Make It Do Something" feature: one working contact
form, backed by a real FastAPI backend and MongoDB.

## What it does

1. Visitor fills in name, email, message and hits Send.
2. `POST /api/contact` validates the fields and inserts a document into
   MongoDB (`lead_capture` database, `leads` collection).
3. `GET /api/leads` reads them back — this is how you can prove a real
   submission actually arrived.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# fill in MONGODB_URI in .env — any MongoDB cluster works, including a free
# MongoDB Atlas cluster
```

## Run locally

```bash
uvicorn index:app --reload
```

Open http://127.0.0.1:8000, submit the form, then open
http://127.0.0.1:8000/api/leads to see it saved.

## Deploy (Render, free tier)

- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `uvicorn index:app --host 0.0.0.0 --port $PORT`
- **Environment Variable:** `MONGODB_URI` = your connection string

## How the data flows (plain words)

The browser only ever talks to this server — it never touches the database
directly. When the form is submitted, the browser sends the three fields as
JSON to `/api/contact`. The server checks nothing is empty, then writes one
document into MongoDB with a timestamp. Nothing is sent back to the visitor
except a success/error message — the actual stored data is only visible to
whoever can reach `/api/leads` (or the database itself), which is exactly
how a real lead-capture form is supposed to work: the visitor submits, the
owner (not the visitor) is the one who later reads the list.
