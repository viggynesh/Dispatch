# agents/alert_agent.py

from seed_data import INITIAL_NEEDS
from dotenv import load_dotenv
from uuid import uuid4
from datetime import datetime, timezone
from uagents_core.contrib.protocols.chat import (
    ChatMessage, ChatAcknowledgement, TextContent,
    EndSessionContent, chat_protocol_spec,
)
from uagents import Agent, Context, Model, Protocol
import sys
import os
import json
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


load_dotenv()

ORCHESTRATOR_ADDRESS = "agent1q0jatv3pu2gm0ed4j9rydtqggkf952ww4c0flyt0raxw2rl0w6wtjk5u8wp"

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

# ── Autonomous escalation loop ───────────────────────────────────────────────


@alert_agent.on_interval(period=30.0)
async def check_unmatched_critical(ctx: Context):
    needs = json.loads(ctx.storage.get("active_needs") or "{}")
    now = datetime.now(timezone.utc)

    escalations = []
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
            escalations.append(
                {"need": need, "wait_minutes": round(wait_seconds / 60, 1)})

    if not escalations:
        ctx.logger.info(
            f"Alert check: no escalations ({len(needs)} needs monitored)")
        return

    ctx.logger.warning(
        f"⚠️ ESCALATING {len(escalations)} unmatched critical needs!")

    alert_lines = [
        f"• [{e['need']['id']}] {e['need']['description']} — waiting {e['wait_minutes']} min — contact: {e['need']['contact']}"
        for e in escalations
    ]

    alert_text = (
        f"⚠️ DISPATCH ALERT — {len(escalations)} CRITICAL NEED(S) UNMATCHED\n\n"
        f"The following urgent requests have had no resource assigned:\n\n"
        + "\n".join(alert_lines) +
        f"\n\nImmediate action required."
    )

    if ORCHESTRATOR_ADDRESS != "PASTE_ORCHESTRATOR_ADDRESS_HERE":
        await ctx.send(ORCHESTRATOR_ADDRESS, ChatMessage(
            timestamp=datetime.now(timezone.utc),
            msg_id=uuid4(),
            content=[TextContent(type="text", text=alert_text)]
        ))
    else:
        ctx.logger.warning(f"ALERT (no orchestrator set):\n{alert_text}")

# ── Chat protocol (only for acks) ────────────────────────────────────────────

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
