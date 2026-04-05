# test.py
import asyncio
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatMessage, ChatAcknowledgement, TextContent,
    EndSessionContent, chat_protocol_spec,
)
from datetime import datetime, timezone
from uuid import uuid4

ORCHESTRATOR_ADDRESS = "agent1q0jatv3pu2gm0ed4j9rydtqggkf952ww4c0flyt0raxw2rl0w6wtjk5u8wp"

test_agent = Agent(
    name="dispatch_test_client",
    seed="dispatch_test_client_seed_999",
    port=8099,
    endpoint=["http://127.0.0.1:8099/submit"],
)

proto = Protocol(spec=chat_protocol_spec)


@test_agent.on_event("startup")
async def send_query(ctx: Context):
    ctx.logger.info("Sending test query to orchestrator...")
    await ctx.send(ORCHESTRATOR_ADDRESS, ChatMessage(
        timestamp=datetime.now(timezone.utc),
        msg_id=uuid4(),
        content=[TextContent(type="text",
                             text="Wildfire in Altadena. Need shelter for 40 people, transport for elderly residents, and insulin for 3 diabetics within 10 miles.")]
    ))


@proto.on_message(ChatMessage)
async def handle_response(ctx: Context, sender: str, msg: ChatMessage):
    for item in msg.content:
        if hasattr(item, "text"):
            ctx.logger.info(f"\n{'='*50}\nRESPONSE:\n{item.text}\n{'='*50}")
        if hasattr(item, "type") and item.type == "end-session":
            ctx.logger.info("Session complete.")


@proto.on_message(ChatAcknowledgement)
async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass

test_agent.include(proto)

if __name__ == "__main__":
    test_agent.run()
