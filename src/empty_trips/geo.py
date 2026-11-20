"""Small geometry helpers. Distances are great-circle (haversine) kilometres."""

from __future__ import annotations

import itertools
import math

EARTH_RADIUS_KM = 6371.0088

Point = tuple[float, float]  # (lat, lon) in degrees


def haversine_km(a: Point, b: Point) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def offset_km(p: Point, north_km: float, east_km: float) -> Point:
    """Move a point a few km north/east (flat-earth approximation, fine at this scale)."""
    lat, lon = p
    return (lat + north_km / 111.32, lon + east_km / (111.32 * math.cos(math.radians(lat))))


def interpolate(a: Point, b: Point, f: float) -> Point:
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)


def polyline_km(points: list[Point]) -> float:
    return sum(haversine_km(p, q) for p, q in itertools.pairwise(points))
