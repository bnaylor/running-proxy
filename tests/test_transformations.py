"""Tests for pure transformation functions (parse, haversine, splits, HR recovery)."""
import pytest
from datetime import datetime, timedelta, timezone

# These imports will fail until transformations.py is created — that's the RED state.
from transformations import (
    parse_workout_datetime,
    haversine_miles,
    calculate_splits_from_route,
    calculate_hr_recovery,
)
from models import HeartRateDataPoint, WorkoutRoutePoint


# ---------------------------------------------------------------------------
# parse_workout_datetime
# ---------------------------------------------------------------------------

def test_parse_workout_datetime_negative_offset():
    """Timestamp with -0400 should be timezone-aware with the correct local hour."""
    dt = parse_workout_datetime("2026-04-08 17:07:32 -0400")
    assert dt.utcoffset() is not None
    assert dt.hour == 17
    assert dt.minute == 7
    assert dt.second == 32


def test_parse_workout_datetime_utc():
    """Timestamp with +0000 should be timezone-aware UTC."""
    dt = parse_workout_datetime("2026-03-30 12:24:54 +0000")
    assert dt.utcoffset().total_seconds() == 0
    assert dt.hour == 12


def test_parse_workout_datetime_negative_and_utc_are_equivalent():
    """Same moment expressed in two offsets should compare equal."""
    dt_local = parse_workout_datetime("2026-04-08 17:07:32 -0400")
    dt_utc = parse_workout_datetime("2026-04-08 21:07:32 +0000")
    assert dt_local == dt_utc


# ---------------------------------------------------------------------------
# haversine_miles
# ---------------------------------------------------------------------------

def test_haversine_same_point_is_zero():
    assert haversine_miles(43.0, -79.0, 43.0, -79.0) == 0.0


def test_haversine_one_mile_at_equator():
    """~0.01447 degrees longitude at the equator ≈ 1 mile."""
    dist = haversine_miles(0.0, 0.0, 0.0, 0.014472)
    assert abs(dist - 1.0) < 0.005  # within 26 feet


# ---------------------------------------------------------------------------
# calculate_splits_from_route
# ---------------------------------------------------------------------------

def _make_route(num_seconds: int, lat1=0.0, lon1=0.0, lat2=0.0, lon2=0.014500):
    """Generate evenly-spaced GPS route points.

    Default lon2=0.014500 covers ~1.002 miles at the equator so the 1-mile
    split boundary is reliably crossed.
    """
    start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    if num_seconds == 0:
        return [WorkoutRoutePoint(
            latitude=lat1, longitude=lon1, altitude=0.0,
            timestamp=start.strftime("%Y-%m-%d %H:%M:%S +0000"), speed=0.0,
        )]
    return [
        WorkoutRoutePoint(
            latitude=lat1 + (lat2 - lat1) * i / num_seconds,
            longitude=lon1 + (lon2 - lon1) * i / num_seconds,
            altitude=0.0,
            timestamp=(start + timedelta(seconds=i)).strftime("%Y-%m-%d %H:%M:%S +0000"),
            speed=0.0,
        )
        for i in range(num_seconds + 1)
    ]


def test_calculate_splits_empty_route():
    assert calculate_splits_from_route([]) == []


def test_calculate_splits_single_point():
    pts = _make_route(0)  # start == end, 1 point
    assert calculate_splits_from_route(pts) == []


def test_calculate_splits_one_mile_8min():
    """480 seconds over ~1 mile should give a single 8:00 split."""
    pts = _make_route(480)
    splits = calculate_splits_from_route(pts)
    assert len(splits) == 1
    minutes, seconds = splits[0].split(":")
    total_sec = int(minutes) * 60 + int(seconds)
    assert abs(total_sec - 480) <= 2  # within 2 seconds of 8:00


def test_calculate_splits_two_miles():
    """960 seconds over ~2 miles should give two splits."""
    pts = _make_route(960, lon2=0.029000)  # ~2.004 miles
    splits = calculate_splits_from_route(pts)
    assert len(splits) == 2


def test_calculate_splits_short_route_no_full_mile():
    """Route shorter than 1 mile produces no splits."""
    # Half a mile only
    pts = _make_route(240, lon2=0.007200)
    splits = calculate_splits_from_route(pts)
    assert splits == []


# ---------------------------------------------------------------------------
# calculate_hr_recovery
# ---------------------------------------------------------------------------

def test_calculate_hr_recovery_uses_one_minute_window():
    """CR = first reading minus the reading closest to workout_end + 60s."""
    end_time = datetime(2026, 4, 8, 21, 17, 39, tzinfo=timezone.utc)  # 17:17:39 -0400
    recovery_data = [
        HeartRateDataPoint(Avg=106, date="2026-04-08 17:17:41 -0400"),  # +2s (start)
        HeartRateDataPoint(Avg=83,  date="2026-04-08 17:18:32 -0400"),  # +53s
        HeartRateDataPoint(Avg=88,  date="2026-04-08 17:18:40 -0400"),  # +61s  ← closest to +60s
        HeartRateDataPoint(Avg=92,  date="2026-04-08 17:19:37 -0400"),  # +118s (too far)
    ]
    result = calculate_hr_recovery(recovery_data, end_time)
    assert result == 106 - 88  # 18 bpm drop


def test_calculate_hr_recovery_empty_returns_zero():
    end_time = datetime(2026, 4, 8, 21, 17, 39, tzinfo=timezone.utc)
    assert calculate_hr_recovery([], end_time) == 0


def test_calculate_hr_recovery_single_point_returns_zero():
    """Only one reading — can't compute a drop."""
    end_time = datetime(2026, 4, 8, 21, 17, 39, tzinfo=timezone.utc)
    data = [HeartRateDataPoint(Avg=106, date="2026-04-08 17:17:41 -0400")]
    assert calculate_hr_recovery(data, end_time) == 0
