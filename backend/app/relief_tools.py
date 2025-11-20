"""
Custom relief tools used by ResQ-AI agents.
Provides lightweight, deterministic fallbacks so the system can keep
running even when LLM access is unavailable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple

import random


# --- Mocked resource inventory ------------------------------------------------

_UNIT_REGISTRY: List[Dict[str, str]] = [
    {
        "id": "Fire-1",
        "type": "fire",
        "location": "Station Alpha",
        "capabilities": {"structure", "industrial"},
        "base_eta": 5,
    },
    {
        "id": "Fire-2",
        "type": "fire",
        "location": "Station Bravo",
        "capabilities": {"wildfire", "structure"},
        "base_eta": 7,
    },
    {
        "id": "Ambulance-2",
        "type": "ems",
        "location": "Medic Hub",
        "capabilities": {"medical", "triage"},
        "base_eta": 6,
    },
    {
        "id": "Rescue-3",
        "type": "rescue",
        "location": "Urban SAR",
        "capabilities": {"collapse", "water"},
        "base_eta": 8,
    },
]

_UNIT_STATUS: Dict[str, Dict[str, Optional[str]]] = {
    unit["id"]: {"status": "available", "incident_id": None, "last_updated": datetime.utcnow()}
    for unit in _UNIT_REGISTRY
}

_SECTOR_MODIFIERS: Dict[str, int] = {
    "sector 1": 3,
    "sector 2": 4,
    "sector 3": 5,
    "sector 4": 6,
    "sector 5": 7,
    "sector 6": 8,
    "sector 7": 4,
    "sector 8": 5,
}


# --- Utility helpers ----------------------------------------------------------

def _normalize(value: Optional[str]) -> str:
    return (value or "unknown").strip().lower()


def _estimate_arrival_minutes(unit: Dict[str, str], location: Optional[str]) -> int:
    sector = _normalize(location)
    modifier = _SECTOR_MODIFIERS.get(sector, 6)
    eta = unit.get("base_eta", 6)
    jitter = random.randint(-1, 1)
    return max(3, eta + modifier // 2 + jitter)


def _score_unit(unit: Dict[str, str], incident: Dict[str, str]) -> float:
    incident_type = _normalize(incident.get("type"))
    urgency = _normalize(incident.get("urgency"))
    score = 0.0

    if incident_type and incident_type in unit["capabilities"]:
        score += 4
    if incident_type in unit["type"]:
        score += 3
    if urgency in {"critical", "high"}:
        score += 2
    return score


# --- Public helpers -----------------------------------------------------------

def get_available_units(unit_type: Optional[str] = None, limit: Optional[int] = None) -> List[Dict[str, str]]:
    """
    Return currently available units, optionally filtered by type and limit.
    """
    candidates = []
    for unit in _UNIT_REGISTRY:
        status = _UNIT_STATUS[unit["id"]]["status"]
        if status != "available":
            continue
        if unit_type and _normalize(unit_type) not in unit["type"]:
            continue
        enriched = dict(unit)
        enriched["eta_minutes"] = _estimate_arrival_minutes(unit, unit.get("location"))
        candidates.append(enriched)

    candidates.sort(key=lambda u: u["eta_minutes"])
    if limit:
        candidates = candidates[:limit]
    return candidates


def recommend_units_for_incident(incident: Dict[str, str], limit: int = 2) -> List[Dict[str, str]]:
    """
    Rank units for an incident and return the top matches.
    """
    ranked: List[Tuple[float, Dict[str, str]]] = []
    for unit in get_available_units(limit=None):
        score = _score_unit(unit, incident)
        if score <= 0:
            continue
        ranked.append((score, unit))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [unit for _, unit in ranked[:limit]]


def generate_incident_brief(incident: Dict[str, str]) -> str:
    incident_type = incident.get("type", "Incident")
    location = incident.get("location", "unknown area")
    details = incident.get("details") or incident.get("description") or ""
    urgency = incident.get("urgency", "CRITICAL")
    extra = f" Details: {details}" if details else ""
    return f"{incident_type} at {location} - urgency {urgency}.{extra}".strip()


def plan_relief_response(incident: Dict[str, str], limit: int = 2) -> Dict[str, str]:
    """
    Deterministic fallback response used when LLM output is unavailable.
    """
    summary = generate_incident_brief(incident)
    ranked_units = recommend_units_for_incident(incident, limit=limit)
    location = incident.get("location", "the scene")

    if ranked_units:
        recommendation = f"Dispatch {ranked_units[0]['id']} to {location}."
        resources = [unit["id"] for unit in ranked_units]
        desc = ", ".join(
            f"{unit['id']} ({unit['type']}, ETA {unit['eta_minutes']}m)" for unit in ranked_units
        )
        resource_summary = f"Primary assignments: {desc}"
    else:
        recommendation = "Hold and escalate to manual supervisor; no units free."
        resources = []
        resource_summary = "All units busy; advise manual review."

    return {
        "summary": summary,
        "recommendation": recommendation,
        "resources": resources,
        "resource_summary": resource_summary,
    }


def format_display_alert(summary: str, recommendation: str, incident: Optional[Dict[str, str]] = None,
                         urgency: Optional[str] = None) -> str:
    """
    Generate a <=60 char alert suitable for the hardware display.
    """
    incident = incident or {}
    urgency = urgency or incident.get("urgency", "CRITICAL")
    location = incident.get("location", "")
    incident_type = incident.get("type", "")
    base = f"{urgency} {incident_type} {location}".strip()
    tail = recommendation or summary
    message = f"{base}: {tail}".strip()
    return (message[:57] + "...") if len(message) > 60 else message


def notify_dispatch(unit_id: str, incident: Dict[str, str]) -> Dict[str, str]:
    """
    Simulate notifying downstream systems about a dispatch event.
    Updates the in-memory registry and returns a record for logging.
    """
    record = {
        "unit_id": unit_id,
        "incident_id": incident.get("id"),
        "location": incident.get("location"),
        "timestamp": datetime.utcnow().isoformat(),
        "status": "queued",
    }
    if unit_id in _UNIT_STATUS:
        _UNIT_STATUS[unit_id]["status"] = "assigned"
        _UNIT_STATUS[unit_id]["incident_id"] = incident.get("id")
        _UNIT_STATUS[unit_id]["last_updated"] = datetime.utcnow()
    print(f"[ReliefTools] Dispatching {unit_id} to {record['location']} (incident {record['incident_id']})")
    return record


def release_unit(unit_id: str) -> None:
    if unit_id in _UNIT_STATUS:
        _UNIT_STATUS[unit_id]["status"] = "available"
        _UNIT_STATUS[unit_id]["incident_id"] = None
        _UNIT_STATUS[unit_id]["last_updated"] = datetime.utcnow()
