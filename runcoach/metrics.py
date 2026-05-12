"""Generic run metrics: pace formatting, HR zone bucketing.

Source-agnostic helpers (used by both the Garmin FIT parser and the Strava
JSON parser) live here. FIT-specific parsing is in `runcoach.fit`.
"""

# HR zones as fraction-of-max-HR boundaries. Index i defines the upper bound
# of zone i. Zones: 1 = recovery, 2 = aerobic base, 3 = aerobic, 4 = threshold,
# 5 = VO2max. Anything above the highest boundary is also zone 5.
HR_ZONE_BOUNDARIES = [0.50, 0.60, 0.70, 0.80, 0.90, 1.0]


def pace_from_speed(speed_m_per_s: float | None) -> str:
    """Convert metres-per-second to a `"M:SS"` per-km string.

    Returns `""` for zero, negative, or None — the calling JSON schema
    treats an empty string as "no pace available" (e.g., a stopped lap).
    """
    if not speed_m_per_s or speed_m_per_s <= 0:
        return ""
    sec_per_km = 1000 / speed_m_per_s
    mins = int(sec_per_km // 60)
    secs = int(sec_per_km % 60)
    return f"{mins}:{secs:02d}"


def pace_from_distance_time(distance_m: float | None, time_s: float | None) -> str:
    """Pace from raw distance + elapsed-time inputs (used for the Strava path
    which derives pace from elapsed time rather than moving time)."""
    if not distance_m or not time_s or distance_m <= 0 or time_s <= 0:
        return ""
    return pace_from_speed(distance_m / time_s)


def pace_to_sec(pace: str | None) -> int | None:
    """Parse `"M:SS"` back to total seconds. Returns None on malformed input.

    Used when comparing lap paces against each other (e.g., for negative-split
    detection). Note: round-trips through this lose fractional-second precision,
    so callers that need sharp comparisons should keep speed/time as floats and
    only format to strings at the end.
    """
    if not pace:
        return None
    try:
        m, s = pace.split(":")
        return int(m) * 60 + int(s)
    except (ValueError, AttributeError):
        return None


def get_hr_zone(hr: float | None, max_hr: float | None) -> int:
    """Return HR zone 1–5 for a sample HR against a runner's max HR.

    Returns 0 when either input is missing (lets callers distinguish "no zone
    available" from "in zone 1"). Note: max_hr should be the *runner's true
    max*, not the per-workout observed max — see the project review for why
    that distinction matters.
    """
    if not hr or not max_hr:
        return 0
    pct = hr / max_hr
    for i, boundary in enumerate(HR_ZONE_BOUNDARIES[1:], start=1):
        if pct <= boundary:
            return i
    return 5
