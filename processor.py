"""
processor.py — Data loading and evaluation pipeline for ViSTA Simulation Format Validator.

    evaluate()
    ├── load_vut()              VUT_status → DataFrame
    ├── validate_vut()          Format checks
    ├── load_actors()           Environment_actors_true → DataFrame (if present)
    ├── validate_actors()       Format checks (if present)
    └── trajectory dicts        lat / lng / heading / t arrays for the map

VUT — Vehicle Under Test
"""
from __future__ import annotations

import io
from typing import Any

import numpy as np
import pandas as pd

import config
from validator import validate_vut, validate_actors, validate_trailer_vut

# Columns required in the actor DataFrame to build trajectory arrays.
_ACTOR_TRAJ_REQUIRED = frozenset({"Actor_pos_true_lat", "Actor_pos_true_lng", "Step_number"})


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def _read_tabular(file_bytes: bytes) -> pd.DataFrame:
    """Load file bytes as either XLSX or CSV, auto-detected from magic header.

    CSV encoding is tried as UTF-8 first, then latin-1 as a fallback so that
    Windows-1252 exports (common from Excel "Save as CSV") are handled correctly.
    """
    if file_bytes[:4] == b'PK\x03\x04':
        return pd.read_excel(io.BytesIO(file_bytes), engine='openpyxl')
    try:
        return pd.read_csv(io.BytesIO(file_bytes), encoding='utf-8')
    except UnicodeDecodeError:
        return pd.read_csv(io.BytesIO(file_bytes), encoding='latin-1')


def load_vut(file_bytes: bytes) -> pd.DataFrame:
    """Parse VUT_status bytes → clean DataFrame.

    Strips whitespace from column names, drops Unnamed columns, adds relative
    time column ``t = Time - Time[0]``, and derives ``VUT_vel_ms`` / ``VUT_vel_kmh``.
    """
    df = _read_tabular(file_bytes)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
    if "Time" in df.columns and len(df) > 0:
        df["t"] = df["Time"] - df["Time"].iloc[0]
    else:
        df["t"] = 0.0
    if "VUT_vel_abs" in df.columns:
        df["VUT_vel_ms"]  = df["VUT_vel_abs"].fillna(0.0)
        df["VUT_vel_kmh"] = df["VUT_vel_ms"] * 3.6
    return df


def load_actors(file_bytes: bytes) -> pd.DataFrame:
    """Parse Environment_actors_true bytes → long-format DataFrame.

    Strips and cleans column names; reconstructs ``Actor_vel_abs`` from
    velocity components where the stored value is zero but components exist.
    """
    df = _read_tabular(file_bytes)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
    if ("Actor_vel_abs" in df.columns
            and "Actor_vel_lat" in df.columns
            and "Actor_vel_lng" in df.columns):
        zero_mask = df["Actor_vel_abs"].fillna(0) == 0
        df.loc[zero_mask, "Actor_vel_abs"] = np.sqrt(
            df.loc[zero_mask, "Actor_vel_lat"].fillna(0) ** 2
            + df.loc[zero_mask, "Actor_vel_lng"].fillna(0) ** 2
        )
    return df


def _vut_has_trailer_data(file_bytes: bytes) -> bool:
    """Return True if VUT_status contains at least one non-null Trailer_pos_lat value."""
    try:
        df = _read_tabular(file_bytes)
        df.columns = [str(c).strip() for c in df.columns]
        return (
            "Trailer_pos_lat" in df.columns
            and bool(df["Trailer_pos_lat"].notna().any())
        )
    except Exception:
        return False


def load_trailer(df: pd.DataFrame) -> dict[str, Any]:
    """Build trailer timeseries dict from Trailer_* columns in a loaded VUT DataFrame.

    Returns:
        Dict with keys ``t``, ``lat``, ``lng``, ``heading`` as float lists.
    """
    def _safe(name: str) -> list[float]:
        if name not in df.columns:
            return [0.0] * len(df)
        return pd.to_numeric(df[name], errors='coerce').fillna(0.0).round(6).tolist()

    return {
        "t": (
            pd.to_numeric(df["t"], errors='coerce').fillna(0.0).round(6).tolist()
            if "t" in df.columns else [0.0] * len(df)
        ),
        "lat":     _safe("Trailer_pos_lat"),
        "lng":     _safe("Trailer_pos_lng"),
        "heading": _safe("Trailer_heading"),
    }


def extract_actors(file_bytes: bytes) -> list[dict]:
    """Return the distinct actors found in an actor file.

    Returns an empty list if the file has no data rows or lacks an Actor_Id column.
    """
    df = load_actors(file_bytes)
    if "Actor_Id" not in df.columns:
        return []
    result = []
    for aid in df["Actor_Id"].unique():
        rows  = df[df["Actor_Id"] == aid]
        atype = int(rows["Actor_type"].iloc[0]) if "Actor_type" in rows.columns else 0
        result.append({
            "actor_id":        str(aid),
            "actor_type":      atype,
            "actor_type_name": config.ACTOR_TYPE_NAMES.get(atype, f"type_{atype}"),
        })
    return result


# ---------------------------------------------------------------------------
# Vectorised column extraction helper (module-level for reuse)
# ---------------------------------------------------------------------------

def _to_float_list(series: pd.Series, decimals: int, default: float = 0.0) -> list[float]:
    """Series → rounded float list; non-numeric/NaN values replaced with default.

    Vectorised — avoids per-row Python iteration on large DataFrames.
    """
    return pd.to_numeric(series, errors='coerce').fillna(default).round(decimals).tolist()


# ---------------------------------------------------------------------------
# Full evaluation pipeline
# ---------------------------------------------------------------------------

def evaluate(
    vut_bytes:    bytes,
    actor_bytes:  bytes | None,
    test_case_id: str,
    run_id:       str,
    vehicle_mode: str = "rigid",
) -> dict[str, Any]:
    """Validate and extract trajectory data for one simulation run.

    Args:
        vut_bytes:    Raw bytes of VUT_status.xlsx/csv.
        actor_bytes:  Raw bytes of Environment_actors_true.xlsx/csv, or None.
        test_case_id: Human-readable test case identifier.
        run_id:       Human-readable run identifier.
        vehicle_mode: ``"rigid"`` or ``"articulated"``. Articulated mode validates
                      Trailer_* columns and includes trailer timeseries in the result.

    Returns:
        Dict with keys:
            ``test_case_id``, ``run_id``,
            ``validation`` — {valid, errors, warnings},
            ``vut``        — timeseries arrays for all VUT channels,
            ``actors``     — list of {actor_id, actor_type, actor_type_name, trajectory},
            ``trailer``    — trailer timeseries {t, lat, lng, heading} (articulated only).
    """
    vut_df = load_vut(vut_bytes)

    # Validate VUT format
    vut_errors, vut_warnings = validate_vut(vut_df)
    all_errors:   list[str] = list(vut_errors)
    all_warnings: list[str] = list(vut_warnings)

    if vehicle_mode == "articulated":
        te, tw = validate_trailer_vut(vut_df)
        all_errors.extend(te)
        all_warnings.extend(tw)

    def _safe_col(name: str, decimals: int = 6, default: float = 0.0) -> list[float]:
        if name not in vut_df.columns:
            return [default] * len(vut_df)
        return _to_float_list(vut_df[name], decimals, default)

    vut_data: dict[str, Any] = {
        "t":              _safe_col("t"),
        "lat":            _safe_col("VUT_pos_lat"),
        "lng":            _safe_col("VUT_pos_lng"),
        "heading":        _safe_col("VUT_heading"),
        "vel_ms":         _safe_col("VUT_vel_ms"),
        "vel_kmh":        _safe_col("VUT_vel_kmh"),
        "accl_lat":       _safe_col("VUT_accl_lat"),
        "accl_lng":       _safe_col("VUT_accl_lng"),
        "braking_level":  _safe_col("VUT_braking_level"),
        "throttle_level": _safe_col("VUT_throttle_level"),
        "steering_pct":   _safe_col("VUT_steering_angle_percentage"),
        "ind_left":       _safe_col("VUT_ind_st_dir_left"),
        "ind_right":      _safe_col("VUT_ind_st_dir_right"),
        "ind_hazard":     _safe_col("VUT_ind_st_hazard"),
        "ind_reverse":    _safe_col("VUT_ind_st_reverse"),
        "ind_braking":    _safe_col("VUT_ind_st_braking"),
    }

    actors_result: list[dict[str, Any]] = []

    if actor_bytes is not None:
        actor_df = load_actors(actor_bytes)

        actor_errors, actor_warnings = validate_actors(actor_df)
        all_errors.extend(actor_errors)
        all_warnings.extend(actor_warnings)

        if "Actor_Id" in actor_df.columns and _ACTOR_TRAJ_REQUIRED.issubset(actor_df.columns):
            # Build a step → t lookup once (O(n)) to avoid O(n²) per-actor scans.
            step_to_t: dict = (
                dict(zip(vut_df["Step_number"], vut_df["t"]))
                if "Step_number" in vut_df.columns
                else {}
            )
            for aid in actor_df["Actor_Id"].unique():
                a_rows = actor_df[actor_df["Actor_Id"] == aid]
                atype  = int(a_rows["Actor_type"].iloc[0]) if "Actor_type" in a_rows.columns else 0

                trajectory: dict[str, Any] = {
                    "lat":     _to_float_list(a_rows["Actor_pos_true_lat"], 6),
                    "lng":     _to_float_list(a_rows["Actor_pos_true_lng"], 6),
                    "heading": (
                        _to_float_list(a_rows["Actor_heading_true"], 4)
                        if "Actor_heading_true" in a_rows.columns
                        else [0.0] * len(a_rows)
                    ),
                    "t": a_rows["Step_number"].map(step_to_t).fillna(0.0).round(4).tolist(),
                }

                actors_result.append({
                    "actor_id":        str(aid),
                    "actor_type":      atype,
                    "actor_type_name": config.ACTOR_TYPE_NAMES.get(atype, f"type_{atype}"),
                    "trajectory":      trajectory,
                })

    validation = {
        "valid":    len(all_errors) == 0,
        "errors":   all_errors,
        "warnings": all_warnings,
    }

    result: dict[str, Any] = {
        "test_case_id": test_case_id,
        "run_id":       run_id,
        "validation":   validation,
        "vut":          vut_data,
        "actors":       actors_result,
    }

    if vehicle_mode == "articulated":
        result["trailer"] = load_trailer(vut_df)

    return result
