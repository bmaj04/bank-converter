import hashlib
import hmac
import io
import json
import os
import uuid

import httpx
import pandas as pd
import pdfplumber
from dotenv import load_dotenv
from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from classify import add_type, summarize
from convert import NoTablesFound, UnsupportedLayout, parse_statement

load_dotenv()  # reads backend/.env on your laptop; on Render the values come from its settings

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "")
PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET_KEY", "")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
PAYSTACK_API = "https://api.paystack.co"

# Credit packs. Prices are in kobo (100 kobo = 1 naira) and live ONLY here on the server,
# so a customer can never choose their own price. Change these numbers to set your pricing.
PACKS = {
    "p50": {"label": "Starter", "credits": 50, "amount_kobo": 300000},      # N3,000
    "p200": {"label": "Standard", "credits": 200, "amount_kobo": 1000000},  # N10,000
    "p600": {"label": "Pro", "credits": 600, "amount_kobo": 2400000},       # N24,000
}

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


async def auth_user(authorization):
    """Check the login token with Supabase and return the user (id and email)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Please sign in to continue.")
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
    return r.json()


async def current_user(authorization):
    return (await auth_user(authorization))["id"]


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


# ---------------------------------------------------------------------------
# Payments (Paystack)
# ---------------------------------------------------------------------------

class CheckoutBody(BaseModel):
    pack: str


class VerifyBody(BaseModel):
    reference: str


async def db_get_payment(reference):
    try:
        async with _client() as client:
            r = await client.get(
                f"{SUPABASE_URL}/rest/v1/payments",
                params={"select": "*", "reference": f"eq.{reference}"},
                headers=_server_headers(),
            )
        r.raise_for_status()
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Could not look up the payment. Try again.")
    rows = r.json()
    return rows[0] if rows else None


async def db_insert_payment(row):
    try:
        async with _client() as client:
            r = await client.post(
                f"{SUPABASE_URL}/rest/v1/payments",
                json=row,
                headers={**_server_headers(), "Prefer": "return=minimal"},
            )
        r.raise_for_status()
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Could not start the payment. Try again.")


async def db_fulfill(reference):
    """Mark a payment paid and add its credits, once. Returns credits added, or -1 if already done."""
    try:
        async with _client() as client:
            r = await client.post(
                f"{SUPABASE_URL}/rest/v1/rpc/fulfill_payment",
                json={"p_reference": reference},
                headers=_server_headers(),
            )
        r.raise_for_status()
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Could not add your credits. Try again.")
    return int(r.json())


async def paystack_call(method, path, json_body=None):
    headers = {"Authorization": f"Bearer {PAYSTACK_SECRET}", "Content-Type": "application/json"}
    try:
        async with _client() as client:
            if method == "GET":
                r = await client.get(f"{PAYSTACK_API}{path}", headers=headers)
            else:
                r = await client.post(f"{PAYSTACK_API}{path}", headers=headers, json=json_body)
        data = r.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(status_code=502, detail="The payment service is not responding.")
    if r.status_code >= 400 or not data.get("status"):
        raise HTTPException(status_code=502, detail="The payment service refused the request.")
    return data["data"]


async def fulfill_if_valid(reference, paid_amount, paid_currency):
    """Give credits only if the amount and currency match what we asked for. Returns credits added."""
    payment = await db_get_payment(reference)
    if payment is None:
        return 0
    if payment["amount_kobo"] != paid_amount or payment["currency"] != paid_currency:
        return 0  # amount mismatch: never give credits
    added = await db_fulfill(reference)
    return max(added, 0)


@app.get("/packs")
def packs():
    return [
        {"id": pid, "label": p["label"], "credits": p["credits"], "amount_kobo": p["amount_kobo"]}
        for pid, p in PACKS.items()
    ]


@app.post("/checkout")
async def checkout(body: CheckoutBody, authorization: str = Header(default=None)):
    """Start a Paystack payment for a credit pack and return the page to send the customer to."""
    user = await auth_user(authorization)
    pack = PACKS.get(body.pack)
    if pack is None:
        raise HTTPException(status_code=400, detail="Unknown credit pack.")

    reference = "sf_" + uuid.uuid4().hex
    await db_insert_payment(
        {
            "reference": reference,
            "user_id": user["id"],
            "pack": body.pack,
            "credits": pack["credits"],
            "amount_kobo": pack["amount_kobo"],
            "currency": "NGN",
        }
    )
    data = await paystack_call(
        "POST",
        "/transaction/initialize",
        {
            "email": user.get("email") or "customer@example.com",
            "amount": pack["amount_kobo"],
            "currency": "NGN",
            "reference": reference,
            "callback_url": FRONTEND_URL,
            "metadata": {"user_id": user["id"], "pack": body.pack},
        },
    )
    return {"authorization_url": data["authorization_url"], "reference": reference}


@app.post("/checkout/verify")
async def checkout_verify(body: VerifyBody, authorization: str = Header(default=None)):
    """Called when the customer comes back from Paystack. Safe to call more than once."""
    user_id = await current_user(authorization)
    payment = await db_get_payment(body.reference)
    if payment is None or payment["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Payment not found.")

    added = 0
    if payment["status"] != "paid":
        data = await paystack_call("GET", f"/transaction/verify/{body.reference}")
        if data.get("status") == "success":
            added = await fulfill_if_valid(body.reference, data.get("amount"), data.get("currency"))
    return {"credits_added": added, "credits": await get_credits(user_id)}


@app.post("/paystack/webhook")
async def paystack_webhook(request: Request, x_paystack_signature: str = Header(default=None)):
    """Paystack calls this itself when a payment succeeds, even if the customer closes the page."""
    raw = await request.body()
    expected = hmac.new(PAYSTACK_SECRET.encode(), raw, hashlib.sha512).hexdigest()
    if not PAYSTACK_SECRET or not hmac.compare_digest(expected, x_paystack_signature or ""):
        raise HTTPException(status_code=401, detail="Bad signature.")

    event = json.loads(raw)
    if event.get("event") == "charge.success":
        data = event.get("data", {})
        await fulfill_if_valid(data.get("reference"), data.get("amount"), data.get("currency"))
    return {"received": True}