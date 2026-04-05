# agents/alert_agent.py

from seed_data import INITIAL_NEEDS
from dotenv import load_dotenv
from uuid import uuid4
from datetime import datetime, timezone
from uagents_core.contrib.protocols.chat import (
    ChatMessage, ChatAcknowledgement, TextContent,
    chat_protocol_spec,
)
from uagents import Agent, Context, Model, Protocol
import sys
import os
import json
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


load_dotenv()

alert_agent = Agent(
    name="dispatch_alert_agent",
    seed="dispatch_alert_agent_seed_diamondhacks_2026",
    port=8003,
    mailbox=True,
)

ALERT_THRESHOLD_SECONDS = 120

# ── Message models ───────────────────────────────────────────────────────────


class NeedSubmission(Model):
    description: str
    urgency: str
    resource_type: str
    lat: float
    lng: float
    contact: str


class NeedMatched(Model):
    need_id: str


class AlertStatusRequest(Model):
    """Orchestrator asks: what critical needs are currently unmatched?"""
    request_id: str


class AlertStatusResponse(Model):
    """Alert agent replies with current unmatched critical needs"""
    message: str
    has_alerts: bool
    request_id: str

# ── Startup ──────────────────────────────────────────────────────────────────


@alert_agent.on_event("startup")
async def load_needs(ctx: Context):
    needs = {}
    now = datetime.now(timezone.utc).isoformat()
    for n in INITIAL_NEEDS:
        n["submitted_at"] = now
        needs[n["id"]] = n
    ctx.storage.set("active_needs", json.dumps(needs))
    ctx.logger.info(f"AlertAgent loaded {len(needs)} initial needs to monitor")

# ── Accept new needs ─────────────────────────────────────────────────────────


@alert_agent.on_message(model=NeedSubmission)
async def handle_new_need(ctx: Context, sender: str, msg: NeedSubmission):
    needs = json.loads(ctx.storage.get("active_needs") or "{}")
    need_id = f"n{len(needs)+100}"
    needs[need_id] = {
        "id": need_id,
        "description": msg.description,
        "urgency": msg.urgency,
        "type": msg.resource_type,
        "lat": msg.lat,
        "lng": msg.lng,
        "contact": msg.contact,
        "matched": False,
        "submitted_at": datetime.now(timezone.utc).isoformat()
    }
    ctx.storage.set("active_needs", json.dumps(needs))
    ctx.logger.info(f"New need registered: {need_id}")

# ── Mark need as matched ─────────────────────────────────────────────────────


@alert_agent.on_message(model=NeedMatched)
async def handle_matched(ctx: Context, sender: str, msg: NeedMatched):
    needs = json.loads(ctx.storage.get("active_needs") or "{}")
    if msg.need_id in needs:
        needs[msg.need_id]["matched"] = True
        ctx.storage.set("active_needs", json.dumps(needs))
        ctx.logger.info(f"Need {msg.need_id} marked as matched")

# ── Answer status requests from orchestrator ─────────────────────────────────


@alert_agent.on_message(model=AlertStatusRequest)
async def handle_status_request(ctx: Context, sender: str, msg: AlertStatusRequest):
    needs = json.loads(ctx.storage.get("active_needs") or "{}")
    now = datetime.now(timezone.utc)

    unmatched = []
    for need in needs.values():
        if need.get("matched"):
            continue
        if need.get("urgency") != "critical":
            continue
        submitted_at = datetime.fromisoformat(need["submitted_at"])
        if submitted_at.tzinfo is None:
            submitted_at = submitted_at.replace(tzinfo=timezone.utc)
        wait_seconds = (now - submitted_at).total_seconds()
        if wait_seconds >= ALERT_THRESHOLD_SECONDS:
            unmatched.append({
                **need,
                "wait_minutes": round(wait_seconds / 60, 1)
            })

    if not unmatched:
        message = "✅ No critical unmatched needs at this time. All monitored needs are either matched or within threshold."
        has_alerts = False
    else:
        lines = [
            f"• [{n['id']}] {n['description']}\n  Waiting: {n['wait_minutes']} min | Contact: {n['contact']}"
            for n in unmatched
        ]
        message = (
            f"⚠️ {len(unmatched)} CRITICAL UNMATCHED NEED(S):\n\n"
            + "\n\n".join(lines)
            + "\n\nThese needs have exceeded the response threshold and require immediate attention."
        )
        has_alerts = True

    ctx.logger.info(
        f"Status request answered: {len(unmatched)} unmatched critical needs")

    await ctx.send(sender, AlertStatusResponse(
        message=message,
        has_alerts=has_alerts,
        request_id=msg.request_id
    ))

# ── Autonomous monitoring loop (stores state, doesn't push) ──────────────────


@alert_agent.on_interval(period=30.0)
async def monitor_needs(ctx: Context):
    """
    Runs autonomously every 30 seconds.
    Tracks escalations internally — doesn't push, waits to be asked.
    """
    needs = json.loads(ctx.storage.get("active_needs") or "{}")
    now = datetime.now(timezone.utc)

    escalation_count = 0
    for need in needs.values():
        if need.get("matched"):
            continue
        if need.get("urgency") != "critical":
            continue
        submitted_at = datetime.fromisoformat(need["submitted_at"])
        if submitted_at.tzinfo is None:
            submitted_at = submitted_at.replace(tzinfo=timezone.utc)
        wait_seconds = (now - submitted_at).total_seconds()
        if wait_seconds >= ALERT_THRESHOLD_SECONDS:
            escalation_count += 1

    if escalation_count > 0:
        ctx.logger.warning(
            f"⚠️ {escalation_count} critical need(s) unmatched beyond threshold — "
            f"stored and ready to report on request"
        )
    else:
        ctx.logger.info(
            f"Monitoring {len(needs)} needs — all within threshold")

# ── Chat protocol ─────────────────────────────────────────────────────────────

chat_proto = Protocol(spec=chat_protocol_spec)


@chat_proto.on_message(ChatMessage)
async def handle_chat(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(sender, ChatAcknowledgement(
        timestamp=datetime.now(timezone.utc),
        acknowledged_msg_id=msg.msg_id
    ))


@chat_proto.on_message(ChatAcknowledgement)
async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass

alert_agent.include(chat_proto, publish_manifest=True)

if __name__ == "__main__":
    print(f"AlertAgent address: {alert_agent.address}")
    alert_agent.run()
