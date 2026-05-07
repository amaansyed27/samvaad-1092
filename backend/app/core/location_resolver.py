"""
Location resolver for Samvaad 1092.

This module is intentionally deterministic for the hackathon demo: it gives the
call flow map-like candidates without depending on a live maps API key. The same
shape can later be backed by Google Places, MapMyIndia, or a government GIS
service.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from math import asin, cos, radians, sin, sqrt
from typing import Any


BENGALURU_BOUNDS = {
    "min_lat": 12.70,
    "max_lat": 13.20,
    "min_lng": 77.35,
    "max_lng": 77.90,
}


KNOWN_CIVIC_PLACES: tuple[dict[str, Any], ...] = (
    {
        "name": "Esplanade Apartments",
        "address": "No. 45, 5th Cross, Indiranagar, Bengaluru, Karnataka 560038",
        "area": "Indiranagar",
        "landmark": "Near Esplanade Apartments on 100 Feet Road",
        "lat": 12.9784,
        "lng": 77.6408,
        "aliases": ("esplanade", "espelad", "esplad", "esplanade apartments", "100 feet road indiranagar"),
    },
    {
        "name": "Vydehi Hospital",
        "address": "Vydehi Hospital, Whitefield, Bengaluru, Karnataka 560066",
        "area": "Whitefield",
        "landmark": "Vydehi Hospital",
        "lat": 12.9757,
        "lng": 77.7280,
        "aliases": ("vydehi", "vydehi hospital", "whitefield hospital", "vydehi whitefield"),
    },
    {
        "name": "Vidhana Soudha",
        "address": "Vidhana Soudha, Ambedkar Veedhi, Bengaluru, Karnataka 560001",
        "area": "Bengaluru",
        "landmark": "Vidhana Soudha",
        "lat": 12.9796,
        "lng": 77.5907,
        "aliases": ("vidhana soudha", "vidhan sabha", "vidhana sabha"),
        "broad": True,
    },
    {
        "name": "Kempegowda International Airport",
        "address": "Kempegowda International Airport, Devanahalli, Bengaluru Rural, Karnataka 560300",
        "area": "Devanahalli",
        "landmark": "Airport",
        "lat": 13.1986,
        "lng": 77.7066,
        "aliases": ("airport", "kempegowda airport", "kempegowda international airport", "kia"),
        "broad": True,
    },
)


def resolve_location_candidates(
    query: str | None,
    *,
    area_hint: str = "",
    geo_pin: dict[str, Any] | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Return ranked location candidates from known local places and optional pin."""
    candidates: list[dict[str, Any]] = []
    query_text = " ".join((query or "").lower().split())
    area_text = (area_hint or "").lower()

    for place in KNOWN_CIVIC_PLACES:
        score = _text_score(query_text, place)
        if area_text and area_text in place["area"].lower():
            score += 0.12
        if geo_pin:
            distance_m = _distance_meters(geo_pin.get("lat"), geo_pin.get("lng"), place["lat"], place["lng"])
            if distance_m is not None:
                if distance_m <= 250:
                    score += 0.25
                elif distance_m <= 1000:
                    score += 0.12
        if score < 0.48:
            continue
        candidate = _candidate_from_place(place, min(score, 0.96))
        candidate["reason"] = "Name or alias matches caller location"
        candidates.append(candidate)

    candidates.sort(key=lambda item: item["confidence"], reverse=True)
    return candidates[:limit]


def candidate_from_geo_pin(pin: dict[str, Any]) -> dict[str, Any]:
    """Normalize a browser/operator map pin into a verified location candidate."""
    lat = _to_float(pin.get("lat"))
    lng = _to_float(pin.get("lng"))
    accuracy = _to_float(pin.get("accuracy_m") or pin.get("accuracy") or 0.0) or 0.0
    address = " ".join(str(pin.get("address") or "").split())
    in_bounds = is_pin_in_bengaluru(lat, lng)
    confidence = 0.88 if in_bounds else 0.55
    if accuracy and accuracy > 250:
        confidence -= 0.12
    name = address or f"Map pin {lat:.5f}, {lng:.5f}"
    return {
        "name": name,
        "address": address or name,
        "area": _area_hint_from_pin(lat, lng) if in_bounds else "",
        "landmark": address or name,
        "lat": lat,
        "lng": lng,
        "confidence": max(0.35, round(confidence, 2)),
        "source": "map_pin",
        "status": "pin_verified" if in_bounds else "pin_outside_service_area",
        "reason": "Caller/operator shared a browser map pin." if in_bounds else "Map pin is outside the expected Bengaluru service area.",
    }


def is_pin_in_bengaluru(lat: float | None, lng: float | None) -> bool:
    if lat is None or lng is None:
        return False
    return (
        BENGALURU_BOUNDS["min_lat"] <= lat <= BENGALURU_BOUNDS["max_lat"]
        and BENGALURU_BOUNDS["min_lng"] <= lng <= BENGALURU_BOUNDS["max_lng"]
    )


def _candidate_from_place(place: dict[str, Any], confidence: float) -> dict[str, Any]:
    return {
        "name": place["name"],
        "address": place["address"],
        "area": place["area"],
        "landmark": place["landmark"],
        "lat": place["lat"],
        "lng": place["lng"],
        "confidence": round(confidence, 2),
        "source": "local_gazetteer",
        "status": "candidate",
        "broad": bool(place.get("broad")),
    }


def _text_score(query: str, place: dict[str, Any]) -> float:
    if not query:
        return 0.0
    haystacks = (place["name"], place["address"], place["landmark"], *place.get("aliases", ()))
    best = 0.0
    for raw in haystacks:
        text = raw.lower()
        if text in query or query in text:
            best = max(best, 0.86)
            continue
        for token in query.split():
            if len(token) >= 4:
                best = max(best, SequenceMatcher(None, token, text).ratio() * 0.82)
        best = max(best, SequenceMatcher(None, query, text).ratio())
    return best


def _distance_meters(lat1: Any, lng1: Any, lat2: Any, lng2: Any) -> float | None:
    lat1_f = _to_float(lat1)
    lng1_f = _to_float(lng1)
    lat2_f = _to_float(lat2)
    lng2_f = _to_float(lng2)
    if None in (lat1_f, lng1_f, lat2_f, lng2_f):
        return None
    radius = 6_371_000
    dlat = radians(lat2_f - lat1_f)
    dlng = radians(lng2_f - lng1_f)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1_f)) * cos(radians(lat2_f)) * sin(dlng / 2) ** 2
    return 2 * radius * asin(sqrt(a))


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _area_hint_from_pin(lat: float, lng: float) -> str:
    nearest = min(
        KNOWN_CIVIC_PLACES,
        key=lambda place: _distance_meters(lat, lng, place["lat"], place["lng"]) or 999_999,
    )
    return nearest["area"]
