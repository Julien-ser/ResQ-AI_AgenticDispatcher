"""
Test file for agentic pipeline: ensures all agents (DispatchAgent, ResourceAgent) work and interact as expected.
Prints verbose output for each step.
"""
import os
from dotenv import load_dotenv
load_dotenv()
from app.agents import (
    get_dispatch_agent,
    get_resource_agent,
    get_multiagent_system,
    Session,
    MultiAgentSystem,
)
from app.relief_tools import plan_relief_response, format_display_alert

# Test data
incident = {
    "type": "Fire",
    "location": "Sector 7",
    "urgency": "CRITICAL"
}


use_gemini = os.getenv("USE_GEMINI", "true").strip().lower() not in {"0", "false", "no", "off"}

if use_gemini:
    print("\n--- Single Agent Test: DispatchAgent (Gemini) ---")
    dispatch_agent = get_dispatch_agent()
    session1 = Session()
    dispatch_result = dispatch_agent.handle_incident(incident, session=session1)
    print("DispatchAgent result:", dispatch_result)
    print("Session history:", session1.history)

    print("\n--- Single Agent Test: ResourceAgent (Gemini) ---")
    resource_agent = get_resource_agent()
    session2 = Session()
    resource_result = resource_agent.handle_incident(incident, session=session2)
    print("ResourceAgent result:", resource_result)
    print("Session history:", session2.history)

    print("\n--- MultiAgentSystem Class Test (Gemini) ---")
    agents_list = [get_dispatch_agent(), get_resource_agent()]
    explicit_multiagent = MultiAgentSystem(agents_list)
    session4 = Session()
    explicit_result = explicit_multiagent.orchestrate(incident, session=session4)
    print("Explicit MultiAgentSystem result:", explicit_result)
    print("Session history:", session4.history)

    print("\n--- Multi-Agent System Test (get_multiagent_system, Gemini) ---")
    multiagent = get_multiagent_system()
    session3 = Session()
    multi_result = multiagent.orchestrate(incident, session=session3)
    print("MultiAgentSystem final result:", multi_result)

    print("\n--- Verbose Pipeline Trace (LLM) ---")
    print("Pipeline: [DispatchAgent -> ResourceAgent]")
    for idx, (user, agent) in enumerate(session3.history):
        print(f"Step {idx+1}: User: {user}\n         Agent: {agent}")

else:
    print("USE_GEMINI is false → Skipping live Gemini tests.")

print("\n--- Relief Tools Offline Test (Deterministic) ---")
plan = plan_relief_response(incident)
print("Fallback plan:", plan)
alert = format_display_alert(plan["summary"], plan["recommendation"], incident, incident.get("urgency", "CRITICAL"))
print("Display alert:", alert)

