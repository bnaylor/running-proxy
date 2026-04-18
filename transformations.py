import math
from datetime import datetime, timedelta
from typing import List, Optional

from models import HeartRateDataPoint, Metric, WorkoutRoutePoint


def parse_workout_datetime(ts: str) -> datetime:
    """Parse a Health Auto Export timestamp into a timezone-aware datetime.

    Handles the format produced by HAE: '2026-04-08 17:07:32 -0400'
    """
    return datetime.strptime(ts.strip(), "%Y-%m-%d %H:%M:%S %z")


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in miles between two GPS coordinates."""
    R = 3958.8  # Earth radius in miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def calculate_splits_from_route(route: List[WorkoutRoutePoint]) -> List[str]:
    """Calculate per-mile pace splits from GPS route points.

    Uses Haversine distance between consecutive points and interpolates
    the exact time at each mile boundary.
    """
    if not route or len(route) < 2:
        return []

    splits = []
    cumulative_dist = 0.0
    next_mile = 1.0

    try:
        last_split_time = parse_workout_datetime(route[0].timestamp)
        prev_time = last_split_time
    except Exception:
        return []

    prev_lat = route[0].latitude
    prev_lon = route[0].longitude

    for point in route[1:]:
        try:
            curr_time = parse_workout_datetime(point.timestamp)
        except Exception:
            continue

        segment_dist = haversine_miles(prev_lat, prev_lon, point.latitude, point.longitude)

        # A single GPS segment could cross multiple mile boundaries (rare)
        while cumulative_dist + segment_dist >= next_mile:
            fraction = (next_mile - cumulative_dist) / segment_dist if segment_dist > 0 else 0
            segment_seconds = (curr_time - prev_time).total_seconds()
            crossing_time = prev_time + timedelta(seconds=fraction * segment_seconds)

            split_sec = round((crossing_time - last_split_time).total_seconds())
            minutes = split_sec // 60
            seconds = split_sec % 60
            splits.append(f"{minutes}:{seconds:02d}")

            last_split_time = crossing_time
            next_mile += 1.0

        cumulative_dist += segment_dist
        prev_lat = point.latitude
        prev_lon = point.longitude
        prev_time = curr_time

    return splits


def calculate_hr_recovery(recovery_data: List[HeartRateDataPoint], end_time: datetime) -> int:
    """HR drop from the first recovery reading to the reading closest to 1 min post-workout.

    Returns 0 if data is missing or insufficient.
    """
    if not recovery_data or len(recovery_data) < 2:
        return 0

    first = recovery_data[0]
    if first.Avg is None:
        return 0
    start_hr = first.Avg

    target_time = end_time + timedelta(seconds=60)
    best_val: Optional[float] = None
    min_diff: Optional[float] = None

    for dp in recovery_data:
        if dp.Avg is None:
            continue
        try:
            dp_time = parse_workout_datetime(dp.date)
            diff = abs((dp_time - target_time).total_seconds())
            if min_diff is None or diff < min_diff:
                min_diff = diff
                best_val = dp.Avg
        except Exception:
            continue

    if best_val is None:
        return 0

    return max(0, int(start_hr - best_val))


# ---------------------------------------------------------------------------
# Helpers used by both main.py and tests
# ---------------------------------------------------------------------------

def f_to_c(f: float) -> float:
    return (f - 32) * 5 / 9


def c_to_f(c: float) -> float:
    return (c * 9 / 5) + 32


def calculate_dew_point(temp_c: float, humidity_pct: float) -> float:
    """Magnus-Tetens formula for dew point, returned in Celsius."""
    if temp_c == 0 or humidity_pct == 0:
        return 0.0
    a, b = 17.625, 243.04
    alpha = ((a * temp_c) / (b + temp_c)) + math.log(humidity_pct / 100.0)
    td = (b * alpha) / (a - alpha)
    return round(td, 1)


def format_duration(seconds: float) -> str:
    from datetime import timedelta
    return str(timedelta(seconds=round(seconds)))


def convert_to_miles(qty: float, unit: Optional[str]) -> float:
    if not unit:
        return qty
    if unit == "km":
        return qty * 0.621371
    if unit == "m":
        return qty * 0.000621371
    if unit == "mi":
        return qty
    return qty


def convert_to_feet(qty: float, unit: Optional[str]) -> float:
    if not unit:
        return qty
    if unit == "m":
        return qty * 3.28084
    if unit == "km":
        return qty * 3280.84
    if unit == "ft":
        return qty
    return qty


def calculate_pace(duration_sec: float, distance_miles: float) -> str:
    """Returns min/mile pace as 'M:SS'."""
    if distance_miles == 0:
        return "0:00"
    pace = (duration_sec / 60) / distance_miles
    minutes = int(pace)
    seconds = int((pace - minutes) * 60)
    return f"{minutes}:{seconds:02d}"


def get_metric_for_date(metrics: List[Metric], name: str, target_date: datetime) -> Optional[float]:
    """Finds the metric value closest to the target date (within 1 day)."""
    best_val = None
    min_diff = timedelta(days=1)
    for m in metrics:
        if m.name == name:
            for d in m.data:
                try:
                    date_val = parse_workout_datetime(d.date)
                    # Compare at midnight-normalized dates (metrics are daily)
                    target_midnight = target_date.replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )
                    # If target is tz-aware, normalize date_val too
                    if target_midnight.tzinfo is not None and date_val.tzinfo is None:
                        from datetime import timezone
                        date_val = date_val.replace(tzinfo=timezone.utc)
                    elif target_midnight.tzinfo is None and date_val.tzinfo is not None:
                        target_midnight = target_midnight.replace(tzinfo=date_val.tzinfo)
                    diff = abs(target_midnight - date_val)
                    if diff <= min_diff:
                        min_diff = diff
                        best_val = d.qty
                except Exception:
                    pass
    return best_val


def map_effort(physical_effort: Optional[float]) -> str:
    """Maps kcal/hr/kg intensity to an AWL label."""
    if physical_effort is None:
        return ""
    if physical_effort < 4.0:
        return "Easy"
    if physical_effort < 8.0:
        return "Moderate"
    return "Hard"
