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
import re
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import config
from processor import evaluate, extract_actors, load_vut, load_actors
from validator import validate_vut, validate_actors

# ---------------------------------------------------------------------------
# Batch store — module-level singleton, lives for the lifetime of the process.
# ---------------------------------------------------------------------------
_batch_store: dict[str, dict[str, dict]] = {}

# ---------------------------------------------------------------------------
# Application instance + static file mounting.
# ---------------------------------------------------------------------------
app = FastAPI(title="ViSTA Simulation Format Validator", version="1.0.0")

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Routes — utility
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the SPA entry point."""
    return (STATIC_DIR / "index.html").read_text()


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
async def batch_upload(zip_file: UploadFile = File(..., description="ZIP archive of test cases")):
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
        If the uploaded file is not a valid ZIP archive.
    """
    global _batch_store
    _batch_store = {}

    try:
        raw = await zip_file.read()
        zf  = zipfile.ZipFile(io.BytesIO(raw))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Cannot open ZIP: {exc}")

    run_pattern = re.compile(r"^(.+)_(r\d+)$")
    names = zf.namelist()

    VUT_NAMES   = {"VUT_status.xlsx",              "VUT_status.csv"}
    ACTOR_NAMES = {"Environment_actors_true.xlsx", "Environment_actors_true.csv"}

    def _is_real_file(name: str, allowed: set) -> bool:
        p = Path(name)
        return (
            p.name in allowed
            and "__MACOSX" not in name
            and not p.name.startswith("._")
        )

    # First pass: build a lookup from parent-dir-name → actor file bytes.
    actor_index: dict[str, bytes] = {}
    for name in names:
        if _is_real_file(name, ACTOR_NAMES):
            parent = Path(name).parent.name
            actor_index[parent] = zf.read(name)

    vut_count   = 0
    valid_runs  = 0
    invalid_runs = 0
    validation_details: dict[str, dict[str, dict]] = {}

    # Second pass: process each VUT file.
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

        # Treat header-only actor files as absent.
        if actor_bytes is not None:
            try:
                if not extract_actors(actor_bytes):
                    actor_bytes = None
            except Exception:
                actor_bytes = None

        # Validate at index time.
        errors:   list[str] = []
        warnings: list[str] = []
        try:
            vut_df = load_vut(vut_bytes)
            ve, vw = validate_vut(vut_df)
            errors.extend(ve)
            warnings.extend(vw)
            if actor_bytes is not None:
                actor_df = load_actors(actor_bytes)
                ae, aw = validate_actors(actor_df)
                errors.extend(ae)
                warnings.extend(aw)
        except Exception as exc:
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
            "vut":        vut_bytes,
            "actor":      actor_bytes,
            "validation": run_validation,
        }
        validation_details.setdefault(tc_id, {})[run_id] = run_validation
        vut_count += 1

    def _run_sort_key(run_id: str) -> int:
        digits = re.sub(r"\D", "", run_id)
        return int(digits) if digits else 0

    sorted_details = {
        tc: dict(sorted(runs.items(), key=lambda kv: _run_sort_key(kv[0])))
        for tc, runs in validation_details.items()
    }

    tc_count     = len(_batch_store)
    overall_valid = (invalid_runs == 0 and vut_count > 0)

    return {
        "overall_valid":      overall_valid,
        "valid_runs":         valid_runs,
        "invalid_runs":       invalid_runs,
        "test_case_count":    tc_count,
        "run_count":          vut_count,
        "test_cases":         list(_batch_store.keys()),
        "validation_details": sorted_details,
    }


@app.delete("/api/batch/clear")
async def batch_clear():
    """Clear the in-memory batch store, freeing all uploaded run data."""
    _batch_store.clear()
    return {"cleared": True}


@app.get("/api/batch/test-cases")
async def batch_test_cases():
    """Return all test case IDs currently loaded in the batch store."""
    result = []
    for tc_id, runs in sorted(_batch_store.items()):
        has_actors = any(r.get("actor") is not None for r in runs.values())
        result.append({"id": tc_id, "has_actors": has_actors})
    return {"test_cases": result}


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
        for run_id, r in sorted(tc.items())
    ]
    return {"runs": runs}


@app.post("/api/batch/evaluate")
async def batch_evaluate(
    test_case_id: str   = Form(...),
    run_id:       str   = Form(...),
):
    """
    Validate and extract trajectory data for a previously uploaded run.

    Returns the validation result (stored at upload time) together with
    the VUT and actor trajectory arrays needed for the visualisation.

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
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Evaluation error: {exc}")

    return JSONResponse(content=result)
