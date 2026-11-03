import io
import os

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from convert import clean_statement, extract_rows, rows_to_dataframe

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


async def read_statement(file: UploadFile) -> pd.DataFrame:
    """Read the uploaded PDF in memory and return the cleaned transactions."""
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF file.")

    data = await file.read()
    if len(data) > MAX_SIZE:
        raise HTTPException(status_code=413, detail="File is too large (10 MB max).")

    try:
        rows = extract_rows(io.BytesIO(data))
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read this PDF.")

    if not rows:
        raise HTTPException(
            status_code=422,
            detail="No tables found. This may be a scanned PDF or an unsupported layout.",
        )

    raw = rows_to_dataframe(rows)
    try:
        return clean_statement(raw)
    except KeyError as missing:
        raise HTTPException(
            status_code=422,
            detail=f"This bank's layout isn't supported yet (missing column {missing}).",
        )


@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/preview")
async def preview(file: UploadFile = File(...)):
    """Return the parsed rows as JSON, for the preview table."""
    clean = await read_statement(file)
    body = (
        '{"count": %d, "total_debits": %s, "total_credits": %s, "rows": %s}'
        % (
            len(clean),
            clean["Debit"].sum(),
            clean["Credit"].sum(),
            clean.to_json(orient="records"),
        )
    )
    return Response(content=body, media_type="application/json")


@app.post("/convert")
async def convert(file: UploadFile = File(...)):
    """Return the cleaned statement as a CSV download."""
    clean = await read_statement(file)
    return Response(
        content=clean.to_csv(index=False),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="statement_clean.csv"'},
    )