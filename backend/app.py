import io
import os

import httpx
import pandas as pd
import pdfplumber
from dotenv import load_dotenv
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from classify import add_type, summarize
from convert import NoTablesFound, UnsupportedLayout, parse_statement

load_dotenv()  # reads backend/.env on your laptop; on Render the values come from its settings

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "")

app = FastAPI(title="Bank Statement Converter")

# Which websites may call this API. Locally it allows your Vite page;
# online, we set ALLOWED_ORIGINS on Render to the Vercel address.
origins = os.getenv(
    "ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in origins],
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_SIZE = 10 * 1024 * 1024  # 10 MB


def _client():
    return httpx.AsyncClient(timeout=15)


def _server_headers():
    # New-style secret keys go in the apikey header ONLY (never in Authorization).
    return {"apikey": SECRET_KEY, "Content-Type": "application/json"}


async def current_user(authorization):
    """Check the login token with Supabase and return the user's id."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Please sign in to convert statements.")
    token = authorization.split(" ", 1)[1].strip()
    try:
        async with _client() as client:
            r = await client.get(
                f"{SUPABASE_URL}/auth/v1/user",
                headers={"Authorization": f"Bearer {token}", "apikey": PUBLISHABLE_KEY},
            )
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Could not reach the login service.")
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Your session has expired. Please sign in again.")
    return r.json()["id"]


async def get_credits(user_id):
    try:
        async with _client() as client:
            r = await client.get(
                f"{SUPABASE_URL}/rest/v1/profiles",
                params={"select": "credits", "id": f"eq.{user_id}"},
                headers=_server_headers(),
            )
        r.raise_for_status()
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Could not check your credits. Try again.")
    rows = r.json()
    return int(rows[0]["credits"]) if rows else 0


async def spend_credits(user_id, pages, layout, rows):
    """Take the credits and log the conversion in one safe step. Returns credits left, or -1."""
    try:
        async with _client() as client:
            r = await client.post(
                f"{SUPABASE_URL}/rest/v1/rpc/spend_credits",
                json={"p_user": user_id, "p_pages": pages, "p_layout": layout, "p_rows": rows},
                headers=_server_headers(),
            )
        r.raise_for_status()
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Could not update your credits. Try again.")
    return int(r.json())


def count_pages(data):
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return max(len(pdf.pages), 1)


async def read_pdf_bytes(file: UploadFile):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF file.")
    data = await file.read()
    if len(data) > MAX_SIZE:
        raise HTTPException(status_code=413, detail="File is too large (10 MB max).")
    return data


async def parse_bytes(data) -> pd.DataFrame:
    try:
        # Parsing can take a few seconds on long statements, so keep it off the event loop.
        clean = await run_in_threadpool(parse_statement, io.BytesIO(data))
        return add_type(clean)
    except NoTablesFound:
        raise HTTPException(
            status_code=422,
            detail="No tables found. This may be a scanned PDF or an unsupported layout.",
        )
    except UnsupportedLayout:
        raise HTTPException(status_code=422, detail="This bank's layout isn't supported yet.")
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read this PDF.")


@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/preview")
async def preview(file: UploadFile = File(...), authorization: str = Header(default=None)):
    """Convert a statement. Needs a login and costs 1 credit per page, charged only on success."""
    user_id = await current_user(authorization)
    data = await read_pdf_bytes(file)

    try:
        pages = await run_in_threadpool(count_pages, data)
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read this PDF.")

    credits = await get_credits(user_id)
    if credits < pages:
        raise HTTPException(
            status_code=402,
            detail=f"This statement has {pages} pages but you only have {credits} credits left.",
        )

    clean = await parse_bytes(data)  # if this fails, nothing is charged

    layout = "wallet" if "Account" in clean.columns else "table"
    left = await spend_credits(user_id, pages, layout, len(clean))
    if left < 0:
        raise HTTPException(status_code=402, detail="You do not have enough credits.")

    stats = summarize(clean)
    body = (
        '{"count": %d, "pages": %d, "credits_left": %d, "total_debits": %s, "total_credits": %s, '
        '"money_in": %s, "money_out": %s, "internal_count": %d, "has_types": %s, "rows": %s}'
        % (
            len(clean),
            pages,
            left,
            round(float(clean["Debit"].sum()), 2),
            round(float(clean["Credit"].sum()), 2),
            stats["money_in"],
            stats["money_out"],
            stats["internal_count"],
            "true" if stats["has_types"] else "false",
            clean.to_json(orient="records"),
        )
    )
    return Response(content=body, media_type="application/json")