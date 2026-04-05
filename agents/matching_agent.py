# agents/matching_agent.py
#
# ROLE: Pure matching logic. Given a set of needs and available resources,
# scores and ranks the best assignments.
# WHY SEPARATE: This is compute logic, not state logic, not communication logic.
# The orchestrator shouldn't do this itself — it would become a god object.
# Isolating matching means you can swap the algorithm without touching anything else.

from dotenv import load_dotenv
from uagents import Agent, Context, Model
import sys
import os
import json
import math
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


load_dotenv()

matching_agent = Agent(
    name="dispatch_matching_agent",
    seed="dispatch_matching_agent_seed_diamondhacks_2026",
    port=8002,
    mailbox=True,
)

# ── Message models ───────────────────────────────────────────────────────────


class MatchRequest(Model):
    """Orchestrator sends: here's what's needed and what's available"""
    needs: str          # JSON: list of {type, description, urgency, lat, lng, count}
    resources: str      # JSON: list of resource dicts from registry
    request_id: str


class MatchResponse(Model):
    """Matching agent returns: ranked assignments"""
    assignments: str    # JSON: list of {need, resource, score, reason}
    unmet_needs: str    # JSON: needs with no good match found
    request_id: str

# ── Scoring logic ────────────────────────────────────────────────────────────


URGENCY_WEIGHT = {"critical": 3, "high": 2, "medium": 1, "low": 0}

TYPE_KEYWORDS = {
    "shelter": ["shelter", "housing", "sleep", "stay", "place", "roof", "beds", "displaced"],
    "transport": ["transport", "vehicle", "car", "bus", "drive", "evacuat", "pickup", "ride", "mobility"],
    "medical": ["medical", "insulin", "medicine", "doctor", "nurse", "emt", "paramedic",
                "diabetic", "oxygen", "dialysis", "cardiac", "injury", "hurt", "wound"],
}


def haversine(lat1, lng1, lat2, lng2) -> float:
    R = 3959
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlng/2)**2)
    return R * 2 * math.asin(math.sqrt(a))


def infer_type(description: str) -> str:
    """Infer resource type from need description"""
    desc_lower = description.lower()
    scores = {}
    for rtype, keywords in TYPE_KEYWORDS.items():
        scores[rtype] = sum(1 for kw in keywords if kw in desc_lower)
    return max(scores, key=scores.get)


def score_match(need: dict, resource: dict) -> float:
    """
    Score how well a resource matches a need (0-100).
    Higher = better match.
    """
    score = 0.0

    # 1. Type match (most important)
    need_type = need.get("type") or infer_type(need.get("description", ""))
    if resource["type"] == need_type:
        score += 40
    else:
        return 0  # wrong type = no match

    # 2. Capacity check
    needed_count = need.get("count", 1)
    if resource["available_capacity"] >= needed_count:
        score += 20
    elif resource["available_capacity"] > 0:
        score += 10  # partial capacity still useful

    # 3. Distance score (closer = better, max 25 points)
    dist = haversine(
        need.get("lat", 34.15), need.get("lng", -118.15),
        resource["lat"], resource["lng"]
    )
    distance_score = max(0, 25 - (dist * 1.5))
    score += distance_score

    # 4. Urgency bonus
    urgency = need.get("urgency", "medium")
    score += URGENCY_WEIGHT.get(urgency, 1) * 3

    # 5. Keyword relevance bonus
    desc_lower = need.get("description", "").lower()
    details_lower = resource.get("details", "").lower()
    keyword_hits = sum(1 for kw in TYPE_KEYWORDS.get(need_type, [])
                       if kw in desc_lower and kw in details_lower)
    score += keyword_hits * 2

    return round(score, 1)


def run_matching(needs: list, resources: list) -> tuple:
    """
    Greedy matching: for each need (sorted by urgency), find best available resource.
    Returns (assignments, unmet_needs)
    """
    # Sort needs by urgency — critical first
    sorted_needs = sorted(needs,
                          key=lambda n: URGENCY_WEIGHT.get(
                              n.get("urgency", "medium"), 1),
                          reverse=True
                          )

    # Track which resources have been assigned
    assigned_resource_ids = set()
    assignments = []
    unmet = []

    for need in sorted_needs:
        best_resource = None
        best_score = 0

        for resource in resources:
            if resource["id"] in assigned_resource_ids:
                continue
            s = score_match(need, resource)
            if s > best_score:
                best_score = s
                best_resource = resource

        if best_resource and best_score >= 40:  # minimum threshold
            assigned_resource_ids.add(best_resource["id"])
            dist = haversine(
                need.get("lat", 34.15), need.get("lng", -118.15),
                best_resource["lat"], best_resource["lng"]
            )
            assignments.append({
                "need": need,
                "resource": best_resource,
                "score": best_score,
                "distance_miles": round(dist, 1),
                "reason": f"Best {best_resource['type']} match within {round(dist, 1)} miles (score: {best_score})"
            })
        else:
            unmet.append(need)

    return assignments, unmet

# ── Message handler ──────────────────────────────────────────────────────────


@matching_agent.on_message(model=MatchRequest)
async def handle_match_request(ctx: Context, sender: str, msg: MatchRequest):
    needs = json.loads(msg.needs)
    resources = json.loads(msg.resources)

    ctx.logger.info(
        f"Running matching: {len(needs)} needs vs {len(resources)} resources")

    assignments, unmet = run_matching(needs, resources)

    ctx.logger.info(
        f"Matched {len(assignments)}/{len(needs)} needs. Unmet: {len(unmet)}")

    await ctx.send(sender, MatchResponse(
        assignments=json.dumps(assignments),
        unmet_needs=json.dumps(unmet),
        request_id=msg.request_id
    ))

if __name__ == "__main__":
    print(f"MatchingAgent address: {matching_agent.address}")
    matching_agent.run()
