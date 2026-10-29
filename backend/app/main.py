"""Aquarient CRM Health — backend API.

Run (from the backend folder):  .venv\\Scripts\\python -m uvicorn app.main:app --reload --port 8000
All routes live under /api/v1, matching the frontend's VITE_API_BASE_URL.
"""
import logging
import threading
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .db import init_db
from .engine import jobs
from fastapi import Depends

from .auth import AuthMiddleware, require_user
from .routers import admin, assessments, assistant, consultant, data, salesforce, uploads, users, workspace

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s: %(message)s")
log = logging.getLogger("aquarient")


@asynccontextmanager
async def lifespan(api: FastAPI):
    init_db()
    s = get_settings()
    log.info("Salesforce app keys in .env: %s (they can also be entered on the Connect Salesforce page)", "yes" if s.salesforce_configured else "no")
    log.info("OAuth callback URL (add this to the Connected App): %s", s.oauth_callback_url)
    stop = threading.Event()
    threads = []
    if s.job_mode == "embedded":
        # Single-machine mode: health checks run on worker threads inside this process.
        threads = jobs.start_threads("embedded", stop, lambda: getattr(api.state, "http_transport", None), recover_host=True)
    else:
        log.info("Health checks run in %s mode%s", s.job_mode, " — start workers with: python -m app.worker" if s.job_mode == "external" else "")
    yield
    stop.set()
    for t in threads:
        t.join(timeout=5)


app = FastAPI(title="Aquarient CRM Health API", version=get_settings().app_version, lifespan=lifespan)

# Resolves the signed-in user for every request and blocks cross-site writes (added first so CORS stays outermost).
app.add_middleware(AuthMiddleware)

# The Vite dev server proxies /api, so CORS only matters if the frontend calls the API directly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().frontend_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Accept"],
)

# Public: health, sign-in and first-run setup. Everything else needs a signed-in user (roles are checked per route).
for r in (workspace.router, users.router):
    app.include_router(r, prefix="/api/v1")
for r in (salesforce.router, uploads.router, assistant.router, data.router, assessments.router, consultant.router, admin.router, admin.requests_router):
    app.include_router(r, prefix="/api/v1", dependencies=[Depends(require_user)])


# One-service hosting: the built website comes from the same server and domain as the API (no CORS, one callback URL).
_site = Path(get_settings().static_dir) if get_settings().static_dir else None
if _site and (_site / "index.html").exists():
    if (_site / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=_site / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def website(path: str):
        """Files in the build (favicon, images…) as they are; any other page is the single-page app."""
        file = (_site / path).resolve()
        if path and not path.startswith("api/") and file.is_file() and _site.resolve() in file.parents:
            return FileResponse(file)
        if path.startswith("api/"):
            raise HTTPException(404, "Not found.")
        return FileResponse(_site / "index.html")
