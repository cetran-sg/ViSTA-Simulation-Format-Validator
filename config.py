# ---------------------------------------------------------------------------
# VUT dimensions
#
# Vh = longitudinal extent (front bumper → rear bumper), metres.
# Vw = lateral extent (left edge → right edge), metres.
# ---------------------------------------------------------------------------
VUT_DIM_LENGTH    = 4.00  # Vh — metres (bumper to bumper)
VUT_DIM_WIDTH     = 1.90  # Vw — metres (edge to edge)

# Offset from CoG to front bumper and left edge; set independently of overall dimensions.
VUT_COG_TO_FRONT  = 2.00  # metres
VUT_COG_TO_LEFT   = 0.95  # metres

# ---------------------------------------------------------------------------
# Actor bounding-box dimensions (length × width, metres).
# Keys are integer Actor_type codes from Environment_actors_true.
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

# VUT absolute velocity limits (km/h) — reference only, not used in validation.
VUT_VELOCITY_ABS_MIN_KMH = 0.0
VUT_VELOCITY_ABS_MAX_KMH = 40.0

# ---------------------------------------------------------------------------
# Articulated (tractor-trailer) mode
# ---------------------------------------------------------------------------

# Columns required in VUT_status when running in Articulated mode.
TRAILER_COLUMNS = [
    "Trailer_pos_lat", "Trailer_pos_lng", "Trailer_pos_z",
    "Trailer_heading", "Trailer_yaw_rate",
    "Trailer_jerk_lat", "Trailer_jerk_lng",
    "Trailer_accl_lat", "Trailer_accl_lng",
    "Trailer_vel_abs",  "Trailer_travelled",
]

# Tractor unit (Class 4 tractor) dimensions
TRACTOR_DIM_LENGTH   = 7.37
TRACTOR_DIM_WIDTH    = 2.54
TRACTOR_COG_TO_FRONT = 3.685
TRACTOR_COG_TO_LEFT  = 1.27

# Trailer unit (ISO semi-trailer) dimensions
TRAILER_DIM_LENGTH   = 12.19
TRAILER_DIM_WIDTH    = 2.44
TRAILER_COG_TO_FRONT = 6.095
TRAILER_COG_TO_LEFT  = 1.22
