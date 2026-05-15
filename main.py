"""
ViSTA Simulation Format Validator — FastAPI backend.

This tool allows AV developers preparing for CETRAN M2 assessment to check
whether their ViSTA-format simulation output is correctly structured before submission.

Routes
------
    GET  /                      Serve the SPA entry point.
    GET  /api/actor-types       Actor type definitions for OBB rendering.
    POST /api/batch/upload      Upload ZIP, validate all runs, index to memory store.
    DELETE /api/batch/clear     Clear the in-memory batch store.
    GET  /api/batch/test-cases  List loaded test case IDs.
    GET  /api/batch/runs/{tc}   List run IDs + validation status for one test case.
    POST /api/batch/evaluate    Evaluate (validate + extract trajectories) one stored run.

Batch store structure::

    _batch_store = {
        "TC_ID": {
            "r0": {
                "vut":        bytes,
                "actor":      bytes | None,
                "validation": {"valid": bool, "errors": [...], "warnings": [...]},
            },
            ...
        },
        ...
    }
"""
from __future__ import annotations

import io
import logging
import re
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

import config
from processor import evaluate, load_vut, load_actors, _vut_has_trailer_data
from validator import validate_vut, validate_actors, validate_trailer_vut

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# In-memory batch store; reset on each upload.
_batch_store: dict[str, dict[str, dict]] = {}

# Vehicle mode, set at upload time.
# 'rigid'       — validates VUT columns only.
# 'articulated' — also validates Trailer_* columns and extracts trailer timeseries.
_vehicle_mode: str = "rigid"

_MAX_UPLOAD_BYTES = 256 * 1024 * 1024  # 256 MB hard limit per upload

STATIC_DIR = Path(__file__).parent / "static"


def _run_sort_key(run_id: str) -> int:
    """Numeric sort key for run IDs like 'r0', 'r1', 'r10'."""
    digits = re.sub(r"\D", "", run_id)
    return int(digits) if digits else 0


# ---------------------------------------------------------------------------
# Security-headers middleware (pure ASGI — works correctly with streaming
# StaticFiles responses, unlike BaseHTTPMiddleware).
# ---------------------------------------------------------------------------
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://unpkg.com https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://unpkg.com; "
    "img-src 'self' data: https:; "
    "connect-src 'self'; "
    "worker-src blob:;"
)


class _SecurityHeadersMiddleware:
    """Injects hardened HTTP response headers on every response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def _send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
                headers["Content-Security-Policy"] = _CSP
            await send(message)

        await self.app(scope, receive, _send)


# ---------------------------------------------------------------------------
# Application instance + static file mounting.
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Fail loudly at startup if any required file is missing."""
    html = STATIC_DIR / "index.html"
    if not html.exists():
        raise RuntimeError(f"Required file not found at startup: {html}")
    logger.info("Startup OK — static/index.html present")
    yield


app = FastAPI(title="ViSTA Simulation Format Validator", version="1.0.0", lifespan=_lifespan)
app.add_middleware(_SecurityHeadersMiddleware)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Routes — utility
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the SPA entry point."""
    return await anyio.Path(STATIC_DIR / "index.html").read_text()


@app.get("/api/actor-types")
async def actor_types():
    """Return actor type definitions for OBB rendering."""
    return {
        "types": [
            {"id": k, "name": v, "dimensions": config.ACTOR_DIMENSIONS.get(k, (1, 1))}
            for k, v in config.ACTOR_TYPE_NAMES.items()
        ]
    }


# ---------------------------------------------------------------------------
# Batch endpoints
# ---------------------------------------------------------------------------

@app.post("/api/batch/upload")
async def batch_upload(
    zip_file:     UploadFile = File(..., description="ZIP archive of test cases"),
    vehicle_mode: str        = Form(default="rigid"),
):
    """
    Accept a ZIP archive, validate all runs, and populate the in-memory batch store.

    Expected ZIP layout
    -------------------
    Each VUT file must be in a directory named ``{test_case_id}_{run_id}``
    where ``run_id`` matches the regex ``r\\d+`` (e.g. ``r0``, ``r1``).

    Example::

        M2-CL4-S-TST-05-02_r0/VUT_status.xlsx
        M2-CL4-S-TST-05-02_r0/Environment_actors_true.xlsx  (optional)

    Response shape::

        {
          "overall_valid":       bool,
          "valid_runs":          int,
          "invalid_runs":        int,
          "test_case_count":     int,
          "run_count":           int,
          "test_cases":          [...],
          "validation_details":  { tc_id: { run_id: {valid, errors, warnings} } }
        }

    Raises
    ------
    400 Bad Request
        If the uploaded file is not a valid ZIP archive, or contains no
        recognised VUT_status files.
    413 Request Entity Too Large
        If the upload exceeds the 256 MB limit.
    """
    global _batch_store, _vehicle_mode
    _batch_store  = {}
    _vehicle_mode = vehicle_mode if vehicle_mode in ("rigid", "articulated") else "rigid"

    raw = await zip_file.read(_MAX_UPLOAD_BYTES + 1)
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Upload exceeds {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit",
        )

    try:
        zf_obj = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="The uploaded file is not a valid ZIP archive")
    except Exception as exc:
        logger.warning("ZIP open failed: %s", exc)
        raise HTTPException(status_code=400, detail="Could not open the uploaded file as a ZIP archive")

    run_pattern = re.compile(r"^(.+)_(r\d+)$")

    VUT_NAMES   = {"VUT_status.xlsx",              "VUT_status.csv"}
    ACTOR_NAMES = {"Environment_actors_true.xlsx", "Environment_actors_true.csv"}

    def _is_real_file(name: str, allowed: set) -> bool:
        p = Path(name)
        return (
            p.name in allowed
            and "__MACOSX" not in name
            and not p.name.startswith("._")
        )

    with zf_obj as zf:
        names = zf.namelist()

        # Index actor files by parent directory name before processing VUT files.
        actor_index: dict[str, bytes] = {}
        for name in names:
            if _is_real_file(name, ACTOR_NAMES):
                parent = Path(name).parent.name
                actor_index[parent] = zf.read(name)

        vut_count   = 0
        valid_runs  = 0
        invalid_runs = 0
        validation_details: dict[str, dict[str, dict]] = {}

        for name in names:
            if not _is_real_file(name, VUT_NAMES):
                continue
            parent = Path(name).parent.name
            m = run_pattern.match(parent)
            if not m:
                continue
            tc_id  = m.group(1)
            run_id = m.group(2)

            vut_bytes   = zf.read(name)
            actor_bytes = actor_index.get(parent)

            # Parse actor file once; treat header-only files as absent.
            cached_actor_df = None
            if actor_bytes is not None:
                try:
                    cached_actor_df = load_actors(actor_bytes)
                    if "Actor_Id" not in cached_actor_df.columns or cached_actor_df.empty:
                        actor_bytes = None
                        cached_actor_df = None
                except Exception:
                    actor_bytes = None
                    cached_actor_df = None

            # Detect trailer data presence (independent of mode selection).
            has_trailer = _vut_has_trailer_data(vut_bytes)

            # Validate at index time.
            errors:   list[str] = []
            warnings: list[str] = []
            try:
                vut_df = load_vut(vut_bytes)
                ve, vw = validate_vut(vut_df)
                errors.extend(ve)
                warnings.extend(vw)
                if _vehicle_mode == "articulated":
                    te, tw = validate_trailer_vut(vut_df)
                    errors.extend(te)
                    warnings.extend(tw)
                if cached_actor_df is not None:
                    ae, aw = validate_actors(cached_actor_df)
                    errors.extend(ae)
                    warnings.extend(aw)
            except Exception as exc:
                logger.warning("Parse error for %s/%s: %s", tc_id, run_id, exc)
                errors.append(f"Failed to parse file: {exc}")

            run_validation = {
                "valid":    len(errors) == 0,
                "errors":   errors,
                "warnings": warnings,
            }

            if run_validation["valid"]:
                valid_runs += 1
            else:
                invalid_runs += 1

            _batch_store.setdefault(tc_id, {})[run_id] = {
                "vut":         vut_bytes,
                "actor":       actor_bytes,
                "has_trailer": has_trailer,
                "validation":  run_validation,
            }
            validation_details.setdefault(tc_id, {})[run_id] = run_validation
            vut_count += 1

    if vut_count == 0:
        raise HTTPException(
            status_code=400,
            detail=(
                "No VUT_status files found in the ZIP. "
                "Expected files named VUT_status.xlsx or VUT_status.csv "
                "inside directories named {TestCaseId}_{runId}/ (e.g. TC_01_r0/)."
            ),
        )

    sorted_details = {
        tc: dict(sorted(runs.items(), key=lambda kv: _run_sort_key(kv[0])))
        for tc, runs in validation_details.items()
    }

    tc_count     = len(_batch_store)
    overall_valid = (invalid_runs == 0 and vut_count > 0)

    has_trailer_any = any(
        r.get("has_trailer", False)
        for tc in _batch_store.values()
        for r in tc.values()
    )

    logger.info(
        "Upload complete: %d TC(s), %d run(s), %d valid, %d invalid, mode=%s",
        tc_count, vut_count, valid_runs, invalid_runs, _vehicle_mode,
    )

    return {
        "overall_valid":      overall_valid,
        "valid_runs":         valid_runs,
        "invalid_runs":       invalid_runs,
        "test_case_count":    tc_count,
        "run_count":          vut_count,
        "test_cases":         list(_batch_store.keys()),
        "validation_details": sorted_details,
        "vehicle_mode":       _vehicle_mode,
        "has_trailer_data":   has_trailer_any,
    }


@app.delete("/api/batch/clear")
async def batch_clear():
    """Clear the in-memory batch store."""
    _batch_store.clear()
    return {"cleared": True}


@app.get("/api/batch/test-cases")
async def batch_test_cases():
    """Return all test case IDs currently loaded in the batch store."""
    result = []
    for tc_id, runs in sorted(_batch_store.items()):
        has_actors  = any(r.get("actor") is not None for r in runs.values())
        has_trailer = any(r.get("has_trailer", False) for r in runs.values())
        result.append({"id": tc_id, "has_actors": has_actors, "has_trailer": has_trailer})
    return {"test_cases": result, "vehicle_mode": _vehicle_mode}


@app.get("/api/batch/runs/{test_case_id:path}")
async def batch_runs(test_case_id: str):
    """Return all run IDs with validation status for a given test case.

    Response shape::

        {
          "runs": [
            {"id": "r0", "has_actors": true, "validation": {valid, errors, warnings}},
            ...
          ]
        }

    Raises
    ------
    404 Not Found
        If ``test_case_id`` is not in the batch store.
    """
    tc = _batch_store.get(test_case_id)
    if tc is None:
        raise HTTPException(status_code=404, detail=f"Test case '{test_case_id}' not found")
    runs = [
        {
            "id":         run_id,
            "has_actors": r.get("actor") is not None,
            "validation": r.get("validation", {"valid": None, "errors": [], "warnings": []}),
        }
        for run_id, r in sorted(tc.items(), key=lambda kv: _run_sort_key(kv[0]))
    ]
    return {"runs": runs}


@app.post("/api/batch/evaluate")
async def batch_evaluate(
    test_case_id: str   = Form(...),
    run_id:       str   = Form(...),
):
    """
    Return trajectory data for a previously uploaded run.

    Response shape::

        {
          "test_case_id": str,
          "run_id":       str,
          "validation":   {"valid": bool, "errors": [...], "warnings": [...]},
          "vut":          {t, lat, lng, heading, vel_kmh, ...},
          "actors":       [{actor_id, actor_type, actor_type_name, trajectory}]
        }

    Raises
    ------
    404 Not Found
        If the test case or run does not exist in the batch store.
    500 Internal Server Error
        If trajectory extraction fails unexpectedly.
    """
    tc = _batch_store.get(test_case_id)
    if tc is None:
        raise HTTPException(status_code=404, detail=f"Test case '{test_case_id}' not found")
    run = tc.get(run_id)
    if run is None:
        raise HTTPException(
            status_code=404,
            detail=f"Run '{run_id}' not found in test case '{test_case_id}'",
        )

    try:
        result = evaluate(
            vut_bytes=run["vut"],
            actor_bytes=run["actor"],
            test_case_id=test_case_id,
            run_id=run_id,
            vehicle_mode=_vehicle_mode,
        )
    except Exception:
        logger.exception("evaluate() failed for %s / %s", test_case_id, run_id)
        raise HTTPException(
            status_code=500,
            detail="Evaluation failed — check the server logs for details",
        )

    return JSONResponse(content=result)
