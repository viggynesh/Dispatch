# run.py — starts all 4 agents together
from uagents import Bureau
from agents.registry_agent import registry_agent
from agents.matching_agent import matching_agent
from agents.alert_agent import alert_agent
from agents.orchestrator import orchestrator

if __name__ == "__main__":
    bureau = Bureau()
    bureau.add(orchestrator)      # port 8000 — ASI:One entry point
    bureau.add(registry_agent)    # port 8001 — stateful resource store
    bureau.add(matching_agent)    # port 8002 — matching algorithm
    bureau.add(alert_agent)       # port 8003 — autonomous escalation
    bureau.run()
