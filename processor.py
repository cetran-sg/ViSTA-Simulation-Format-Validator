"""
processor.py — Simplified evaluation pipeline for ViSTA Simulation Format Validator.

This module loads VUT and actor data, validates their format, and builds
trajectory dictionaries for the visualisation frontend.

Pipeline overview
-----------------
    evaluate()
    ├── load_vut()              Parse VUT_status file → DataFrame
    ├── validate_vut()          Data format checks
    ├── load_actors()           Parse Environment_actors_true → DataFrame (if present)
    ├── validate_actors()       Data format checks (if present)
    └── Build trajectory dicts  lat / lng / heading / t arrays for the map

Naming conventions
------------------
    VUT  — Vehicle Under Test (the AV being evaluated)
"""
from __future__ import annotations

import io
import math
from typing import Any

import numpy as np
import pandas as pd

import config
from validator import validate_vut, validate_actors


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def _read_tabular(file_bytes: bytes) -> pd.DataFrame:
    """Load file bytes as either XLSX or CSV, auto-detected from magic header."""
    if file_bytes[:4] == b'PK\x03\x04':
        return pd.read_excel(io.BytesIO(file_bytes), engine='openpyxl')
    return pd.read_csv(io.BytesIO(file_bytes))


def load_vut(file_bytes: bytes) -> pd.DataFrame:
    """Parse a VUT_status file and return a clean DataFrame.

    Post-processing:
    - Column names stripped of surrounding whitespace.
    - Unnamed columns dropped.
    - Relative time column ``t`` added: ``t = Time - Time[0]``.
    - ``VUT_vel_ms`` and ``VUT_vel_kmh`` derived from ``VUT_vel_abs``.
    """
    df = _read_tabular(file_bytes)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
    df["t"] = df["Time"] - df["Time"].iloc[0]
    if "VUT_vel_abs" in df.columns:
        df["VUT_vel_ms"]  = df["VUT_vel_abs"].fillna(0.0)
        df["VUT_vel_kmh"] = df["VUT_vel_ms"] * 3.6
    return df


def load_actors(file_bytes: bytes) -> pd.DataFrame:
    """Parse an Environment_actors_true file and return a long-format DataFrame.

    Post-processing:
    - Column names stripped and Unnamed columns dropped.
    - ``Actor_vel_abs`` reconstructed from Pythagorean sum of components
      where it is zero but components are available.
    """
    df = _read_tabular(file_bytes)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
    if "Actor_vel_abs" in df.columns and "Actor_vel_lat" in df.columns:
        zero_mask = df["Actor_vel_abs"].fillna(0) == 0
        df.loc[zero_mask, "Actor_vel_abs"] = np.sqrt(
            df.loc[zero_mask, "Actor_vel_lat"].fillna(0) ** 2
            + df.loc[zero_mask, "Actor_vel_lng"].fillna(0) ** 2
        )
    return df


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


def merge_data(vut_df: pd.DataFrame, actor_df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Join VUT telemetry with each actor's rows on Step_number.

    Kept for trajectory alignment use cases. Returns a dict mapping
    str(actor_id) → merged DataFrame.
    """
    merged = {}
    for aid in actor_df["Actor_Id"].unique():
        a      = actor_df[actor_df["Actor_Id"] == aid].copy().set_index("Step_number")
        joined = vut_df.copy().set_index("Step_number")
        joined = joined.join(
            a[["Actor_type", "Actor_pos_true_lat", "Actor_pos_true_lng",
               "Actor_heading_true", "Actor_vel_abs"]],
            how="left",
        ).reset_index()
        valid = joined["Actor_pos_true_lat"].notna()
        merged[str(aid)] = joined[valid].copy()
    return merged


# ---------------------------------------------------------------------------
# Full evaluation pipeline
# ---------------------------------------------------------------------------

def evaluate(
    vut_bytes:    bytes,
    actor_bytes:  bytes | None,
    test_case_id: str,
    run_id:       str,
) -> dict[str, Any]:
    """Validate and extract trajectory data for one simulation run.

    Args:
        vut_bytes:    Raw bytes of VUT_status.xlsx/csv.
        actor_bytes:  Raw bytes of Environment_actors_true.xlsx/csv, or None.
        test_case_id: Human-readable test case identifier.
        run_id:       Human-readable run identifier.

    Returns:
        Dict with keys:
            ``test_case_id``, ``run_id``,
            ``validation`` — {valid, errors, warnings},
            ``vut``        — timeseries arrays for all VUT channels,
            ``actors``     — list of {actor_id, actor_type, actor_type_name, trajectory}.
    """
    vut_df = load_vut(vut_bytes)

    # Validate VUT format
    vut_errors, vut_warnings = validate_vut(vut_df)
    all_errors:   list[str] = list(vut_errors)
    all_warnings: list[str] = list(vut_warnings)

    # Helper: extract a column as a list of rounded floats, defaulting to 0.0 for NaN.
    def safe_col(df: pd.DataFrame, name: str, default: float = 0.0) -> list[float]:
        if name in df.columns:
            return [
                round(float(v), 6)
                if v is not None and not (isinstance(v, float) and math.isnan(v))
                else default
                for v in df[name]
            ]
        return [default] * len(df)

    vut_data: dict[str, Any] = {
        "t":              safe_col(vut_df, "t"),
        "lat":            safe_col(vut_df, "VUT_pos_lat"),
        "lng":            safe_col(vut_df, "VUT_pos_lng"),
        "heading":        safe_col(vut_df, "VUT_heading"),
        "vel_ms":         safe_col(vut_df, "VUT_vel_ms"),
        "vel_kmh":        safe_col(vut_df, "VUT_vel_kmh"),
        "accl_lat":       safe_col(vut_df, "VUT_accl_lat"),
        "accl_lng":       safe_col(vut_df, "VUT_accl_lng"),
        "braking_level":  safe_col(vut_df, "VUT_braking_level"),
        "throttle_level": safe_col(vut_df, "VUT_throttle_level"),
        "steering_pct":   safe_col(vut_df, "VUT_steering_angle_percentage"),
        "ind_left":       safe_col(vut_df, "VUT_ind_st_dir_left"),
        "ind_right":      safe_col(vut_df, "VUT_ind_st_dir_right"),
        "ind_hazard":     safe_col(vut_df, "VUT_ind_st_hazard"),
        "ind_reverse":    safe_col(vut_df, "VUT_ind_st_reverse"),
        "ind_braking":    safe_col(vut_df, "VUT_ind_st_braking"),
    }

    actors_result: list[dict[str, Any]] = []

    if actor_bytes is not None:
        actor_df = load_actors(actor_bytes)

        # Validate actor format
        actor_errors, actor_warnings = validate_actors(actor_df)
        all_errors.extend(actor_errors)
        all_warnings.extend(actor_warnings)

        if "Actor_Id" in actor_df.columns:
            for aid in actor_df["Actor_Id"].unique():
                a_rows = actor_df[actor_df["Actor_Id"] == aid]
                atype  = int(a_rows["Actor_type"].iloc[0]) if "Actor_type" in a_rows.columns else 0

                trajectory: dict[str, Any] = {
                    "lat": [round(float(v), 6) for v in a_rows["Actor_pos_true_lat"]],
                    "lng": [round(float(v), 6) for v in a_rows["Actor_pos_true_lng"]],
                    "heading": (
                        [
                            round(float(v), 4)
                            if not (isinstance(v, float) and math.isnan(v)) else 0.0
                            for v in a_rows["Actor_heading_true"]
                        ]
                        if "Actor_heading_true" in a_rows.columns
                        else [0.0] * len(a_rows)
                    ),
                    # Map each actor Step_number to the VUT's relative time t
                    "t": [
                        round(float(vut_df.loc[vut_df["Step_number"] == s, "t"].values[0]), 4)
                        if s in vut_df["Step_number"].values else 0.0
                        for s in a_rows["Step_number"]
                    ],
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

    return {
        "test_case_id": test_case_id,
        "run_id":       run_id,
        "validation":   validation,
        "vut":          vut_data,
        "actors":       actors_result,
    }
