# agents/orchestrator.py

from agents.alert_agent import NeedMatched, AlertStatusRequest, AlertStatusResponse
from agents.matching_agent import MatchRequest, MatchResponse
from agents.registry_agent import ResourceQuery, ResourceQueryResponse
from dotenv import load_dotenv
import anthropic
from uuid import uuid4
from datetime import datetime, timezone
from uagents_core.contrib.protocols.chat import (
    ChatMessage, ChatAcknowledgement, TextContent,
    EndSessionContent, chat_protocol_spec,
)
from uagents import Agent, Context, Protocol, Model
import sys
import os
import json
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


load_dotenv()

REGISTRY_ADDRESS = "agent1qf6mmellt3pe3cskn45vmvx8v73mcgmrvawqazf2k4thwm0f7nacjcrs09y"
MATCHING_ADDRESS = "agent1qddsu2ldewaxw0xm2zyj6njknrzruzuc38sw76zqdx67df3ue3guqwcta97"
ALERT_ADDRESS = "agent1qwkmk2qcgvdr7wle755gnm4j7ajjh88l4fr0t0u9prwy6pc0cfg9w0em9ac"

orchestrator = Agent(
    name="dispatch_orchestrator",
    seed="dispatch_orchestrator_seed_diamondhacks_2026",
    port=8000,
    mailbox=True,
)

claude = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
chat_proto = Protocol(spec=chat_protocol_spec)

# ── Helpers ──────────────────────────────────────────────────────────────────


def parse_intent(query: str) -> dict:
    resp = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{
            "role": "user",
            "content": f"""Extract disaster relief needs from this query. Reply ONLY with valid JSON, no explanation.

Query: "{query}"

JSON format:
{{
  "needs": [
    {{
      "description": "specific need description",
      "type": "shelter|transport|medical",
      "urgency": "critical|high|medium|low",
      "count": 1,
      "lat": 34.1897,
      "lng": -118.1314
    }}
  ],
  "center_lat": 34.1897,
  "center_lng": -118.1314,
  "radius_miles": 15
}}

Default center: lat 34.1897, lng -118.1314 (Altadena area).
Extract one need object per distinct resource type needed."""
        }]
    )
    try:
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())
    except:
        return {
            "needs": [
                {"description": query, "type": "shelter", "urgency": "high",
                    "count": 1, "lat": 34.1897, "lng": -118.1314},
                {"description": query, "type": "transport", "urgency": "high",
                    "count": 1, "lat": 34.1897, "lng": -118.1314},
                {"description": query, "type": "medical", "urgency": "high",
                    "count": 1, "lat": 34.1897, "lng": -118.1314},
            ],
            "center_lat": 34.1897, "center_lng": -118.1314, "radius_miles": 15
        }


def synthesize_response(query: str, assignments: list, unmet: list) -> str:
    if not assignments and not unmet:
        return "No matching resources found in the area. Please broaden your search radius."

    assignment_text = ""
    for a in assignments:
        n = a["need"]
        r = a["resource"]
        assignment_text += (
            f"\n✅ {n['description']}\n"
            f"   → {r['name']} ({r['type']}, {a['distance_miles']} miles away)\n"
            f"   → Contact: {r['contact']}\n"
            f"   → Details: {r['details']}\n"
        )

    unmet_text = ""
    for u in unmet:
        unmet_text += f"\n❌ UNMET: {u['description']} (urgency: {u.get('urgency', 'unknown')})\n"

    resp = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        messages=[{"role": "user", "content": f"""You are Dispatch, an autonomous disaster coordination AI.
A coordinator submitted: "{query}"

Resource assignments found:
{assignment_text if assignment_text else "None"}

Unmet needs:
{unmet_text if unmet_text else "None"}

Write a concise, actionable coordination plan. Format:
1. Lead with matched resources and immediate actions
2. For each match: what to do, who to call, how far away
3. Flag any unmet needs clearly
4. Keep it under 200 words. Be direct — this is an emergency."""}]
    )
    return resp.content[0].text


def get_session(ctx: Context, req_id: str) -> dict:
    raw = ctx.storage.get(f"session_{req_id}")
    return json.loads(raw) if raw else {}


def save_session(ctx: Context, req_id: str, data: dict):
    ctx.storage.set(f"session_{req_id}", json.dumps(data))


def clear_session(ctx: Context, req_id: str):
    ctx.storage.set(f"session_{req_id}", "")

# ── Chat Protocol: entry point from ASI:One ──────────────────────────────────


@chat_proto.on_message(ChatMessage)
async def handle_chat(ctx: Context, sender: str, msg: ChatMessage):
    # Always ack immediately
    await ctx.send(sender, ChatAcknowledgement(
        timestamp=datetime.now(timezone.utc),
        acknowledged_msg_id=msg.msg_id
    ))

    # Extract text
    user_text = ""
    for item in msg.content:
        if hasattr(item, "text"):
            user_text = item.text
            break

    # Store sender so we can reply later
    ctx.storage.set("last_user_sender", sender)

    # Skip empty messages
    if not user_text or not user_text.strip():
        return

    # Skip ASI:One's own LLM injections
    if len(user_text) > 500:
        return

    ctx.logger.info(f"Orchestrator received: {user_text[:80]}")

    # Handle alert status queries
    alert_keywords = ["alert", "alerts", "unmatched",
                      "critical", "any updates", "status"]
    if any(kw in user_text.lower() for kw in alert_keywords):
        req_id = str(uuid4())[:8]
        ctx.storage.set(f"alert_req_{req_id}", sender)
        await ctx.send(ALERT_ADDRESS, AlertStatusRequest(request_id=req_id))
        await ctx.send(sender, ChatMessage(
            timestamp=datetime.now(timezone.utc),
            msg_id=uuid4(),
            content=[TextContent(
                type="text", text="🔍 Checking alert status...")]
        ))
        return

    # Send interim message
    await ctx.send(sender, ChatMessage(
        timestamp=datetime.now(timezone.utc),
        msg_id=uuid4(),
        content=[TextContent(
            type="text", text="🔍 Dispatch activated. Querying resource registry...")]
    ))

    # Parse intent
    intent = parse_intent(user_text)
    req_id = str(uuid4())[:8]

    save_session(ctx, req_id, {
        "original_query": user_text,
        "sender": sender,
        "needs": intent["needs"],
        "stage": "waiting_registry",
        "resources": None,
    })
    ctx.storage.set("latest_req_id", req_id)

    resource_types = list(set(n["type"] for n in intent["needs"]))
    await ctx.send(REGISTRY_ADDRESS, ResourceQuery(
        resource_types=resource_types,
        center_lat=intent.get("center_lat", 34.1897),
        center_lng=intent.get("center_lng", -118.1314),
        radius_miles=intent.get("radius_miles", 15.0),
        request_id=req_id
    ))
    ctx.logger.info(f"Queried registry for types: {resource_types}")


@chat_proto.on_message(ChatAcknowledgement)
async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass

# ── Alert status response ─────────────────────────────────────────────────────


@orchestrator.on_message(model=AlertStatusResponse)
async def handle_alert_status(ctx: Context, sender: str, msg: AlertStatusResponse):
    original_sender = ctx.storage.get(f"alert_req_{msg.request_id}")
    if original_sender:
        await ctx.send(original_sender, ChatMessage(
            timestamp=datetime.now(timezone.utc),
            msg_id=uuid4(),
            content=[TextContent(type="text", text=msg.message)]
        ))
        ctx.logger.info(
            f"Alert status delivered to user — has_alerts: {msg.has_alerts}")

# ── Registry response → trigger matching ─────────────────────────────────────


@orchestrator.on_message(model=ResourceQueryResponse)
async def handle_registry_response(ctx: Context, sender: str, msg: ResourceQueryResponse):
    req_id = msg.request_id
    session = get_session(ctx, req_id)
    if not session:
        ctx.logger.warning(f"No session found for req_id {req_id}")
        return

    resources = json.loads(msg.resources)
    ctx.logger.info(
        f"Registry returned {len(resources)} resources for req {req_id}")

    session["resources"] = resources
    session["stage"] = "waiting_matching"
    save_session(ctx, req_id, session)

    await ctx.send(session["sender"], ChatMessage(
        timestamp=datetime.now(timezone.utc),
        msg_id=uuid4(),
        content=[TextContent(type="text",
                             text=f"📦 Found {len(resources)} available resources. Running matching algorithm...")]
    ))

    await ctx.send(MATCHING_ADDRESS, MatchRequest(
        needs=json.dumps(session["needs"]),
        resources=json.dumps(resources),
        request_id=req_id
    ))

# ── Match response → synthesize and reply ────────────────────────────────────


@orchestrator.on_message(model=MatchResponse)
async def handle_match_response(ctx: Context, sender: str, msg: MatchResponse):
    req_id = msg.request_id
    session = get_session(ctx, req_id)
    if not session:
        ctx.logger.warning(f"No session found for req_id {req_id}")
        return

    assignments = json.loads(msg.assignments)
    unmet = json.loads(msg.unmet_needs)
    user_sender = session["sender"]

    ctx.logger.info(
        f"Matching complete: {len(assignments)} matched, {len(unmet)} unmet")

    for a in assignments:
        need_id = a["need"].get("id")
        if need_id:
            await ctx.send(ALERT_ADDRESS, NeedMatched(need_id=need_id))

    final_response = synthesize_response(
        session["original_query"], assignments, unmet)

    await ctx.send(user_sender, ChatMessage(
        timestamp=datetime.now(timezone.utc),
        msg_id=uuid4(),
        content=[TextContent(
            type="text", text=f"⚡ DISPATCH COORDINATION PLAN:\n\n{final_response}")]
    ))

    clear_session(ctx, req_id)

orchestrator.include(chat_proto, publish_manifest=True)

if __name__ == "__main__":
    print(f"Orchestrator address: {orchestrator.address}")
    orchestrator.run()
