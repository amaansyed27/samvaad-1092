"""
Location resolver for Samvaad 1092.

This module uses a provider chain:

1. Dynamic geocoder/search provider for arbitrary places the caller says.
2. Optional browser/operator map pin reverse-geocoding.
3. Small local gazetteer fallback for offline hackathon demos.

The returned candidate shape is provider-neutral, so a production deployment can
swap Nominatim for Google Places, MapMyIndia, Karnataka GIS, or BBMP ward data.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from functools import lru_cache
from math import asin, cos, radians, sin, sqrt
from typing import Any

import httpx

from app.config import settings


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
    """Return ranked location candidates from dynamic geocoding plus fallback."""
    query_text = " ".join((query or "").lower().split())
    area_text = (area_hint or "").lower()
    candidates: list[dict[str, Any]] = []

    for resolved in _resolve_dynamic_candidates(query_text, area_hint, limit=limit):
        candidate = dict(resolved)
        candidate["reason"] = "Dynamic geocoder match for caller location"
        candidates.append(candidate)

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
        candidate["reason"] = "Offline fallback name or alias match"
        candidates.append(candidate)

    return _dedupe_and_rank(candidates, limit=limit)


def candidate_from_geo_pin(pin: dict[str, Any]) -> dict[str, Any]:
    """Normalize a browser/operator map pin into a verified location candidate."""
    lat = _to_float(pin.get("lat"))
    lng = _to_float(pin.get("lng"))
    accuracy = _to_float(pin.get("accuracy_m") or pin.get("accuracy") or 0.0) or 0.0
    if lat is None or lng is None:
        return {
            "name": "Invalid map pin",
            "address": "",
            "area": "",
            "landmark": "",
            "lat": lat,
            "lng": lng,
            "confidence": 0.0,
            "source": "map_pin",
            "status": "pin_invalid",
            "reason": "Map pin did not include valid latitude and longitude.",
        }
    address = " ".join(str(pin.get("address") or "").split())
    if not address:
        address = _reverse_geocode_pin(lat, lng)
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


@lru_cache(maxsize=256)
def _resolve_dynamic_candidates(query: str, area_hint: str = "", *, limit: int = 3) -> tuple[dict[str, Any], ...]:
    provider = (settings.location_geocoder_provider or "disabled").lower()
    if provider in {"", "disabled", "offline", "local"}:
        return ()
    if provider != "nominatim":
        return ()
    if not query or len(query) < 4:
        return ()

    search_text = _build_search_query(query, area_hint)
    try:
        response = httpx.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": search_text,
                "format": "jsonv2",
                "addressdetails": 1,
                "limit": max(1, min(limit, 5)),
                "countrycodes": "in",
                "bounded": 1,
                "viewbox": f"{BENGALURU_BOUNDS['min_lng']},{BENGALURU_BOUNDS['max_lat']},{BENGALURU_BOUNDS['max_lng']},{BENGALURU_BOUNDS['min_lat']}",
            },
            headers={"User-Agent": settings.location_geocoder_user_agent},
            timeout=settings.location_geocoder_timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
    except Exception:
        return ()

    candidates: list[dict[str, Any]] = []
    for item in data[:limit]:
        candidate = _candidate_from_nominatim(item, query)
        if candidate:
            candidates.append(candidate)
    return tuple(candidates)


@lru_cache(maxsize=128)
def _reverse_geocode_pin(lat: float, lng: float) -> str:
    provider = (settings.location_geocoder_provider or "disabled").lower()
    if provider != "nominatim":
        return ""
    try:
        response = httpx.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={
                "lat": lat,
                "lon": lng,
                "format": "jsonv2",
                "addressdetails": 1,
                "zoom": 18,
            },
            headers={"User-Agent": settings.location_geocoder_user_agent},
            timeout=settings.location_geocoder_timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
    except Exception:
        return ""
    return " ".join(str(data.get("display_name") or "").split())


def _candidate_from_nominatim(item: dict[str, Any], query: str) -> dict[str, Any] | None:
    lat = _to_float(item.get("lat"))
    lng = _to_float(item.get("lon"))
    if lat is None or lng is None:
        return None
    if not is_pin_in_bengaluru(lat, lng):
        return None

    address = item.get("address") or {}
    name = (
        item.get("name")
        or address.get("amenity")
        or address.get("building")
        or address.get("road")
        or item.get("display_name")
        or "Map search result"
    )
    display = " ".join(str(item.get("display_name") or name).split())
    area = (
        address.get("suburb")
        or address.get("neighbourhood")
        or address.get("city_district")
        or address.get("city")
        or address.get("town")
        or ""
    )
    raw_importance = _to_float(item.get("importance")) or 0.0
    text_score = SequenceMatcher(None, query, display.lower()).ratio()
    confidence = min(0.93, max(0.55, 0.45 + text_score * 0.35 + raw_importance * 0.2))
    category = item.get("category") or item.get("class") or "place"
    place_type = item.get("type") or ""
    broad = place_type in {"city", "state", "county", "airport"} or category in {"boundary"}
    return {
        "name": str(name),
        "address": display,
        "area": str(area),
        "landmark": str(name),
        "lat": lat,
        "lng": lng,
        "confidence": round(confidence, 2),
        "source": "nominatim",
        "status": "candidate",
        "provider": "OpenStreetMap Nominatim",
        "broad": broad,
        "category": category,
        "place_type": place_type,
    }


def _build_search_query(query: str, area_hint: str) -> str:
    suffix_parts = []
    if area_hint and area_hint.lower() not in query:
        suffix_parts.append(area_hint)
    if "bengaluru" not in query and "bangalore" not in query:
        suffix_parts.append("Bengaluru")
    if "karnataka" not in query:
        suffix_parts.append("Karnataka")
    return ", ".join([query, *suffix_parts])


def _dedupe_and_rank(candidates: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    ranked: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        key = _candidate_key(candidate)
        existing = ranked.get(key)
        if not existing or candidate.get("confidence", 0.0) > existing.get("confidence", 0.0):
            ranked[key] = candidate
    ordered = sorted(ranked.values(), key=lambda item: item.get("confidence", 0.0), reverse=True)
    return ordered[:limit]


def _candidate_key(candidate: dict[str, Any]) -> str:
    lat = _to_float(candidate.get("lat"))
    lng = _to_float(candidate.get("lng"))
    if lat is not None and lng is not None:
        return f"{round(lat, 4)}:{round(lng, 4)}"
    return str(candidate.get("address") or candidate.get("name") or "").lower()


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
