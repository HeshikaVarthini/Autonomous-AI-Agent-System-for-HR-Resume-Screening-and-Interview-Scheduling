"""
backend/main.py
===============
FastAPI entry point.
Run:  python main.py
  or: uvicorn main:app --reload --port 8000

Loads .env from this directory (e.g. GROQ_API_KEY for resume scoring).
NOTE: Route registration order matters in FastAPI.
  - API router must be included BEFORE app.mount()
  - app.mount() creates a sub-application that captures ALL unmatched paths
"""

import logging
import os
from pathlib import Path

# Load .env so GROQ_API_KEY (and others) are available
try:
    from dotenv import load_dotenv
    _env = Path(__file__).resolve().parent / ".env"
    if _env.exists():
        load_dotenv(_env)
except ImportError:
    pass

# Log whether Groq LLM will be available (so user sees it in terminal)
_key = os.environ.get("GROQ_API_KEY", "")
if _key:
    _mask = f"{_key[:7]}...{_key[-4:]}" if len(_key) > 12 else "***"
    print(f"  GROQ_API_KEY loaded ({_mask}) — resume scoring will use LLM when job skills are set.")
else:
    print("  GROQ_API_KEY not set — resume scoring will use keyword fallback only.")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from api_forms import router as forms_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(name)s - %(message)s")
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)

app = FastAPI(
    title="Google Form Auto-Watcher",
    description="HR pastes a Google Form link → system watches for responses → downloads resumes automatically.",
    version="1.0.0",
    openapi_tags=[
        {"name": "Forms", "description": "**Forms API** — Connect form, list watchers, check interview responses, job config. Start with `GET /api/forms` to verify, then `POST /api/forms/watch` to connect a Google Form."},
    ],
)

# ── CORS (allow all origins) ──────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 1. API routes FIRST (before any mount) ────────────────────────────────
app.include_router(forms_router)

# ── 2. Health / root endpoints BEFORE mount ───────────────────────────────
@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the frontend UI."""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return HTMLResponse(index_file.read_text(encoding="utf-8"))
    return HTMLResponse(
        "<h1>FormWatcher API is running</h1>"
        "<p>Visit <a href='/docs'>/docs</a> for API docs.</p>"
    )


# ── 3. Static file mount LAST ─────────────────────────────────────────────
# IMPORTANT: mount() must come after all @app.get/@app.post routes
# because it acts as a catch-all sub-application.
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn
    # Disable reload on Windows to avoid subprocess KeyboardInterrupt tracebacks during file watch
    use_reload = os.name != "nt"
    logger.info("Starting server -> http://localhost:8000")
    logger.info("  Frontend : http://localhost:8000")
    logger.info("  API docs : http://localhost:8000/docs")
    logger.info("  Uploads  : backend/uploads/")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=use_reload)

