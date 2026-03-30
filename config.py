import os
import tempfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUTH_DB_PATH    = os.path.join(BASE_DIR, "auth.db")
SAVED_RUNS_DIR  = os.path.join(BASE_DIR, "saved_runs")
UPLOAD_FOLDER   = os.path.join(BASE_DIR, "data")
MPL_CACHE_DIR   = os.path.join(tempfile.gettempdir(), "mpl-cache")

MAX_WELLS_PER_FILE = 25

TIME_UNIT_FACTORS = {
    "hours":   3600.0,
    "minutes":   60.0,
    "seconds":    1.0,
}
TIME_UNIT_SUFFIX = {
    "hours":   "h",
    "minutes": "min",
    "seconds": "s",
}

os.makedirs(SAVED_RUNS_DIR, exist_ok=True)
os.makedirs(UPLOAD_FOLDER,  exist_ok=True)


def normalize_time_unit(value):
    unit = (value or "hours").strip().lower()
    return unit if unit in TIME_UNIT_FACTORS else "hours"


def unit_suffix(unit):
    return TIME_UNIT_SUFFIX.get(normalize_time_unit(unit), "h")


def time_axis_from_seconds(time_sec, unit):
    import numpy as np
    unit = normalize_time_unit(unit)
    arr = np.array(time_sec, dtype=float)
    if len(arr) == 0:
        return np.array([], dtype=float)
    return (arr - float(arr[0])) / TIME_UNIT_FACTORS[unit]


def hours_to_unit(value_hours, unit):
    if value_hours is None:
        return None
    unit = normalize_time_unit(unit)
    return float(value_hours) * (3600.0 / TIME_UNIT_FACTORS[unit])


def unit_to_hours(value_unit, unit):
    if value_unit is None:
        return None
    unit = normalize_time_unit(unit)
    return float(value_unit) * (TIME_UNIT_FACTORS[unit] / 3600.0)
