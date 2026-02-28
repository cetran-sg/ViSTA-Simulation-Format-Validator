"""
validator.py — Data format validation for ViSTA Simulation Format Validator.

Two functions: validate_vut(df) and validate_actors(df).
Each returns (errors: list[str], warnings: list[str]).
valid = len(errors) == 0
"""
from __future__ import annotations

import pandas as pd


VUT_REQUIRED_COLS = [
    "Time",
    "Step_number",
    "VUT_pos_lat",
    "VUT_pos_lng",
    "VUT_heading",
    "VUT_vel_abs",
]

ACTOR_REQUIRED_COLS = [
    "Time",
    "Step_number",
    "Actor_Id",
    "Actor_type",
    "Actor_pos_true_lat",
    "Actor_pos_true_lng",
    "Actor_heading_true",
]


def validate_vut(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    """Validate VUT_status DataFrame for required columns and value ranges.

    Args:
        df: Output of processor.load_vut().

    Returns:
        (errors, warnings). errors is empty when data is valid.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Required columns
    missing = [c for c in VUT_REQUIRED_COLS if c not in df.columns]
    if missing:
        errors.append(f"Missing required columns: {', '.join(missing)}")
        return errors, warnings  # cannot validate further without required columns

    # VUT_pos_lat in range -90 to 90
    lat = df["VUT_pos_lat"].dropna()
    if len(lat) > 0 and ((lat < -90) | (lat > 90)).any():
        errors.append("VUT_pos_lat contains values outside the valid range (-90 to 90)")

    # VUT_pos_lng in range -180 to 360
    lng = df["VUT_pos_lng"].dropna()
    if len(lng) > 0 and ((lng < -180) | (lng > 360)).any():
        errors.append("VUT_pos_lng contains values outside the valid range (-180 to 360)")

    # VUT_heading in range 0 to 360
    heading = df["VUT_heading"].dropna()
    if len(heading) > 0 and ((heading < 0) | (heading > 360)).any():
        errors.append("VUT_heading contains values outside the valid range (0 to 360)")

    # VUT_vel_abs non-negative
    vel = df["VUT_vel_abs"].dropna()
    if len(vel) > 0 and (vel < 0).any():
        errors.append("VUT_vel_abs contains negative values")

    # Time monotonically non-decreasing
    time_vals = df["Time"].dropna()
    if len(time_vals) > 1 and (time_vals.diff().dropna() < 0).any():
        errors.append("Time column is not monotonically non-decreasing")

    # Warn on NaN values in position/heading columns
    for col in ["VUT_pos_lat", "VUT_pos_lng", "VUT_heading"]:
        if col in df.columns and df[col].isna().any():
            nan_count = int(df[col].isna().sum())
            warnings.append(f"{col} has {nan_count} NaN value(s)")

    return errors, warnings


def validate_actors(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    """Validate Environment_actors_true DataFrame for required columns and value ranges.

    Args:
        df: Output of processor.load_actors().

    Returns:
        (errors, warnings). errors is empty when data is valid.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Required columns
    missing = [c for c in ACTOR_REQUIRED_COLS if c not in df.columns]
    if missing:
        errors.append(f"Missing required columns: {', '.join(missing)}")
        return errors, warnings

    # Actor_pos_true_lat in range -90 to 90
    lat = df["Actor_pos_true_lat"].dropna()
    if len(lat) > 0 and ((lat < -90) | (lat > 90)).any():
        errors.append("Actor_pos_true_lat contains values outside the valid range (-90 to 90)")

    # Actor_pos_true_lng in range -180 to 360
    lng = df["Actor_pos_true_lng"].dropna()
    if len(lng) > 0 and ((lng < -180) | (lng > 360)).any():
        errors.append("Actor_pos_true_lng contains values outside the valid range (-180 to 360)")

    # Actor_heading_true in range 0 to 360
    heading = df["Actor_heading_true"].dropna()
    if len(heading) > 0 and ((heading < 0) | (heading > 360)).any():
        errors.append("Actor_heading_true contains values outside the valid range (0 to 360)")

    # Actor_type must be integer-valued
    try:
        actor_types = df["Actor_type"].dropna()
        non_int = actor_types[actor_types.apply(lambda x: not float(x).is_integer())]
        if len(non_int) > 0:
            errors.append("Actor_type contains non-integer values")
    except (ValueError, TypeError):
        errors.append("Actor_type contains non-numeric values")

    return errors, warnings
