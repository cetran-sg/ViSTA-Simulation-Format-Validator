"""
config.py — Tuneable constants for ViSTA Simulation Format Validator.

Physical parameters for the VUT and actor bounding boxes used during
trajectory visualisation.
"""

# ---------------------------------------------------------------------------
# VUT dimensions
#
# Vh = longitudinal extent (front bumper → rear bumper), metres.
# Vw = lateral extent (left edge → right edge), metres.
# ---------------------------------------------------------------------------
VUT_DIM_LENGTH    = 4.00  # Vh — metres (bumper to bumper)
VUT_DIM_WIDTH     = 1.90  # Vw — metres (edge to edge)

# Distance from the CoG to the front bumper and left edge (metres).
# These are used to offset the bounding-box so it is correctly anchored
# at the CoG position reported by the simulation.  They are independent of
# the overall dimensions and must be set per-vehicle.
VUT_COG_TO_FRONT  = 2.00  # metres
VUT_COG_TO_LEFT   = 0.95  # metres

# ---------------------------------------------------------------------------
# Actor bounding-box dimensions (length × width, metres).
#
# Keys are the integer Actor_type codes found in Environment_actors_true.
# Each value is (length_m, width_m) representing the rectangular footprint
# of that actor class.  Used by the frontend to render OBB markers on the map.
# ---------------------------------------------------------------------------
ACTOR_DIMENSIONS: dict[int, tuple[float, float]] = {
    0:  (1.00, 1.00),   # pedestrian / generic VRU
    1:  (2.67, 0.57),   # Personal Mobility Device (PMD / e-scooter)
    2:  (2.67, 0.57),   # cyclist (bicycle)
    3:  (1.00, 1.00),   # animal
    4:  (3.90, 1.65),   # passenger vehicle / Target Scenario Vehicle (TSV)
    5:  (1.63, 0.73),   # motorcycle
    6:  (6.00, 2.50),   # fire truck
    7:  (6.00, 2.50),   # ambulance
    8:  (5.00, 2.00),   # van
    9:  (8.00, 2.50),   # trailer
    10: (8.00, 2.50),   # truck
    11: (12.0, 2.50),   # bus
    20: (0.35, 0.35),   # construction cone / road marker
    99: (1.00, 1.00),   # others / unclassified
}

# ---------------------------------------------------------------------------
# Human-readable names for each actor type code.
# ---------------------------------------------------------------------------
ACTOR_TYPE_NAMES: dict[int, str] = {
    0:  "pedestrian",
    1:  "PMD",
    2:  "cyclist",
    3:  "animal",
    4:  "passenger_vehicle",
    5:  "motorcycle",
    6:  "fire_truck",
    7:  "ambulance",
    8:  "van",
    9:  "trailer",
    10: "truck",
    11: "bus",
    20: "construction_cone",
    99: "others",
}

# ---------------------------------------------------------------------------
# VUT absolute velocity limits (km/h) — informational only.
# These are not used in format validation but are kept as reference constants.
# ---------------------------------------------------------------------------
VUT_VELOCITY_ABS_MIN_KMH = 0.0
VUT_VELOCITY_ABS_MAX_KMH = 40.0
