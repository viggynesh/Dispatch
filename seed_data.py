# seed_data.py
# Pre-loaded LA wildfire scenario data
# This populates the ResourceRegistryAgent on startup

import json
from pathlib import Path

_SCRAPED_FILE = Path(__file__).parent / "scraped_resources.json"


def _load_scraped_resources() -> list[dict] | None:
    """Try to load real scraped data; return None if unavailable."""
    try:
        if _SCRAPED_FILE.exists():
            data = json.loads(_SCRAPED_FILE.read_text())
            if isinstance(data, list) and len(data) > 0:
                return data
    except Exception:
        pass
    return None


INITIAL_RESOURCES = _load_scraped_resources() or [
    {
        "id": "s001",
        "type": "shelter",
        "name": "Pasadena Community Center",
        "capacity": 60,
        "available_capacity": 40,
        "lat": 34.1478, "lng": -118.1445,
        "details": "Has beds, food, medical station, wheelchair accessible",
        "contact": "626-555-0101",
        "status": "available"
    },
    {
        "id": "s002",
        "type": "shelter",
        "name": "Arcadia High School Gym",
        "capacity": 120,
        "available_capacity": 75,
        "lat": 34.1397, "lng": -118.0353,
        "details": "Large facility, beds, food, showers",
        "contact": "626-555-0102",
        "status": "available"
    },
    {
        "id": "s003",
        "type": "shelter",
        "name": "Monrovia Recreation Center",
        "capacity": 40,
        "available_capacity": 2,
        "lat": 34.1442, "lng": -117.9995,
        "details": "Small shelter, nearly full",
        "contact": "626-555-0103",
        "status": "available"
    },
    {
        "id": "t001",
        "type": "transport",
        "name": "Red Cross Bus Unit 7",
        "capacity": 45,
        "available_capacity": 45,
        "lat": 34.1425, "lng": -118.2551,
        "details": "Full-size bus, wheelchair accessible, driver on standby",
        "contact": "626-555-0201",
        "status": "available"
    },
    {
        "id": "t002",
        "type": "transport",
        "name": "Volunteer SUV Fleet (4 vehicles)",
        "capacity": 20,
        "available_capacity": 20,
        "lat": 34.1808, "lng": -118.3089,
        "details": "4 SUVs, not wheelchair accessible, available immediately",
        "contact": "626-555-0202",
        "status": "available"
    },
    {
        "id": "t003",
        "type": "transport",
        "name": "LA County Emergency Van",
        "capacity": 12,
        "available_capacity": 12,
        "lat": 34.0953, "lng": -118.1270,
        "details": "Accessible van, trained driver, medical equipment on board",
        "contact": "626-555-0203",
        "status": "available"
    },
    {
        "id": "m001",
        "type": "medical",
        "name": "Altadena Clinic Supply Cache",
        "capacity": 999,
        "available_capacity": 999,
        "lat": 34.1897, "lng": -118.1314,
        "details": "Insulin, syringes, glucometers, test strips — 30-day supply for 10 patients",
        "contact": "626-555-0301",
        "status": "available"
    },
    {
        "id": "m002",
        "type": "medical",
        "name": "Volunteer Paramedic Team",
        "capacity": 999,
        "available_capacity": 999,
        "lat": 34.1614, "lng": -118.0531,
        "details": "3 EMTs, first aid, oxygen, defibrillator, general medications",
        "contact": "626-555-0302",
        "status": "available"
    },
    {
        "id": "m003",
        "type": "medical",
        "name": "Kaiser Emergency Warehouse",
        "capacity": 999,
        "available_capacity": 999,
        "lat": 34.1433, "lng": -118.1553,
        "details": "Dialysis supplies, IV fluids, cardiac monitors, general pharmaceuticals",
        "contact": "626-555-0303",
        "status": "available"
    },
]

if _load_scraped_resources():
    print(f"[seed_data] Loaded {len(INITIAL_RESOURCES)} resources from {_SCRAPED_FILE.name}")
else:
    print("[seed_data] Using hardcoded fallback resources")

# Active needs — simulates real disaster requests already in the system
# AlertAgent will monitor these for unmatched critical ones
INITIAL_NEEDS = [
    {
        "id": "n001",
        "description": "Insulin delivery needed urgently for diabetic evacuee",
        "type": "medical",
        "urgency": "critical",
        "lat": 34.1897, "lng": -118.1314,
        "contact": "626-555-1001",
        "matched": False,
        "submitted_at": None  # set at runtime
    },
    {
        "id": "n002",
        "description": "Elderly couple needs evacuation, no vehicle, mobility issues",
        "type": "transport",
        "urgency": "critical",
        "lat": 34.1350, "lng": -118.0200,
        "contact": "626-555-1002",
        "matched": False,
        "submitted_at": None
    },
    {
        "id": "n003",
        "description": "Family of 5 needs shelter, have a dog",
        "type": "shelter",
        "urgency": "high",
        "lat": 34.1600, "lng": -118.1000,
        "contact": "626-555-1003",
        "matched": False,
        "submitted_at": None
    },
]
