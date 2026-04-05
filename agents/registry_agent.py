# agents/registry_agent.py
#
# ROLE: Stateful resource registry. Holds live availability of all resources.
# WHY SEPARATE: It maintains state across the lifetime of the system.
# The orchestrator doesn't hold state — the registry does.
# Resources can register, update, and deregister independently.
# This is fundamentally different from "run a query and return."

from seed_data import INITIAL_RESOURCES
from dotenv import load_dotenv
from uagents import Agent, Context, Model
import sys
import os
import json
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


load_dotenv()

registry_agent = Agent(
    name="dispatch_registry_agent",
    seed="dispatch_registry_agent_seed_diamondhacks_2026",
    port=8001,
    mailbox=True,
)

# ── Message models ──────────────────────────────────────────────────────────


class ResourceQuery(Model):
    """Orchestrator asks: what resources match this type/area?"""
    resource_types: list   # e.g. ["shelter", "transport", "medical"]
    center_lat: float
    center_lng: float
    radius_miles: float = 15.0
    request_id: str        # echoed back so orchestrator can match responses


class ResourceQueryResponse(Model):
    """Registry replies with matching resources"""
    resources: str         # JSON string of matching resource list
    request_id: str


class ResourceUpdate(Model):
    """Any agent can update a resource's availability"""
    resource_id: str
    available_capacity: int
    status: str            # "available" or "unavailable"


class ResourceRegister(Model):
    """Register a brand new resource at runtime"""
    resource: str          # JSON string of resource dict

# ── Helpers ─────────────────────────────────────────────────────────────────


def haversine(lat1, lng1, lat2, lng2) -> float:
    import math
    R = 3959
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlng/2)**2)
    return R * 2 * math.asin(math.sqrt(a))


def load_registry(ctx: Context) -> dict:
    raw = ctx.storage.get("resources")
    if not raw:
        return {}
    return json.loads(raw)


def save_registry(ctx: Context, registry: dict):
    ctx.storage.set("resources", json.dumps(registry))

# ── Startup: seed the registry ───────────────────────────────────────────────


@registry_agent.on_event("startup")
async def seed_registry(ctx: Context):
    registry = load_registry(ctx)
    if not registry:
        for r in INITIAL_RESOURCES:
            registry[r["id"]] = r
        save_registry(ctx, registry)
        ctx.logger.info(f"Registry seeded with {len(registry)} resources")
    else:
        ctx.logger.info(
            f"Registry loaded with {len(registry)} existing resources")

# ── Handle resource queries from orchestrator ────────────────────────────────


@registry_agent.on_message(model=ResourceQuery)
async def handle_query(ctx: Context, sender: str, msg: ResourceQuery):
    registry = load_registry(ctx)

    matching = []
    for r in registry.values():
        # Filter by type
        if r["type"] not in msg.resource_types:
            continue
        # Filter by availability
        if r["status"] != "available" or r["available_capacity"] <= 0:
            continue
        # Filter by distance
        dist = haversine(msg.center_lat, msg.center_lng, r["lat"], r["lng"])
        if dist <= msg.radius_miles:
            matching.append({**r, "distance_miles": round(dist, 1)})

    matching.sort(key=lambda x: x["distance_miles"])
    ctx.logger.info(
        f"Query matched {len(matching)} resources for types {msg.resource_types}")

    await ctx.send(sender, ResourceQueryResponse(
        resources=json.dumps(matching),
        request_id=msg.request_id
    ))

# ── Handle resource updates ──────────────────────────────────────────────────


@registry_agent.on_message(model=ResourceUpdate)
async def handle_update(ctx: Context, sender: str, msg: ResourceUpdate):
    registry = load_registry(ctx)
    if msg.resource_id in registry:
        registry[msg.resource_id]["available_capacity"] = msg.available_capacity
        registry[msg.resource_id]["status"] = msg.status
        save_registry(ctx, registry)
        ctx.logger.info(
            f"Updated resource {msg.resource_id}: capacity={msg.available_capacity}, status={msg.status}")

# ── Handle new resource registrations ───────────────────────────────────────


@registry_agent.on_message(model=ResourceRegister)
async def handle_register(ctx: Context, sender: str, msg: ResourceRegister):
    registry = load_registry(ctx)
    resource = json.loads(msg.resource)
    registry[resource["id"]] = resource
    save_registry(ctx, registry)
    ctx.logger.info(f"Registered new resource: {resource['name']}")

# ── Periodic status log ──────────────────────────────────────────────────────


@registry_agent.on_interval(period=60.0)
async def status_report(ctx: Context):
    registry = load_registry(ctx)
    available = [r for r in registry.values() if r["status"] == "available"]
    ctx.logger.info(
        f"Registry status: {len(available)}/{len(registry)} resources available")

if __name__ == "__main__":
    print(f"RegistryAgent address: {registry_agent.address}")
    registry_agent.run()
