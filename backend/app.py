import io
import os

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from convert import NoTablesFound, UnsupportedLayout, parse_statement

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
        # Parsing can take a few seconds on long statements, so keep it off the event loop.
        return await run_in_threadpool(parse_statement, io.BytesIO(data))
    except NoTablesFound:
        raise HTTPException(
            status_code=422,
            detail="No tables found. This may be a scanned PDF or an unsupported layout.",
        )
    except UnsupportedLayout:
        raise HTTPException(
            status_code=422,
            detail="This bank's layout isn't supported yet.",
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read this PDF.")


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
            round(float(clean["Debit"].sum()), 2),
            round(float(clean["Credit"].sum()), 2),
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