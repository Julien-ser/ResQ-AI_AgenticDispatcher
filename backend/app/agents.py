# --- Decision Agent for SEND/HOLD/Queue Management ---

# --- Decision Agent for SEND/HOLD/Queue Management (A2A compatible) ---
class DecisionAgent:
    def __init__(self, name="Decision-Agent"):
        self.name = name
        self.history = []  # List of {action, status, timestamp, incident_id}

    def handle_envelope(self, envelope, session=None):
        import datetime
        # Accepts MessageEnvelope, expects 'action' and 'incident_id' in content
        content = envelope.content
        action = content.get("action")
        incident_id = content.get("incident_id")
        status = "success" if action in ["SEND", "HOLD"] else "error"
        message = f"Action {action} processed" if status == "success" else f"Unknown action: {action}"
        entry = {
            "action": action,
            "status": status,
            "message": message,
            "incident_id": incident_id,
            "timestamp": datetime.datetime.now().isoformat()
        }
        self.history.append(entry)
        self.history = self.history[-10:]
        content["decision_status"] = status
        content["decision_message"] = message
        envelope.add_trace(self.name, entry)
        envelope.content = content
        return envelope

    def handle_decision(self, action, incident_id=None):
        # For legacy direct calls
        import datetime
        status = "success" if action in ["SEND", "HOLD"] else "error"
        message = f"Action {action} processed" if status == "success" else f"Unknown action: {action}"
        entry = {
            "action": action,
            "status": status,
            "message": message,
            "incident_id": incident_id,
            "timestamp": datetime.datetime.now().isoformat()
        }
        self.history.append(entry)
        self.history = self.history[-10:]
        return entry

    def get_history(self):
        return self.history

def get_decision_agent():
    # Singleton pattern for global state
    if not hasattr(get_decision_agent, "_agent"):
        get_decision_agent._agent = DecisionAgent()
    return get_decision_agent._agent
"""
Agent logic for ResQ-AI Dispatch System.
Defines agent classes, reasoning, and orchestration.
"""



# Agentic pipeline concepts: session, memory, observability, evaluation, multi-agent orchestration
import os
import time
import uuid
from typing import List, Dict, Any
from loguru import logger
import google.generativeai as genai

from app.relief_tools import (
    format_display_alert,
    get_available_units,
    notify_dispatch,
    plan_relief_response,
)

# --- Gemini API Setup ---
GOOGLE_API_KEY = os.getenv("API_KEY")
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)

USE_GEMINI = os.getenv("USE_GEMINI", "true").strip().lower() not in {"0", "false", "no", "off"}
GEMINI_BACKOFF_SECONDS = int(os.getenv("GEMINI_BACKOFF_SECONDS", "45"))
_gemini_backoff_until = 0.0


def _gemini_available() -> bool:
    return bool(GOOGLE_API_KEY) and USE_GEMINI and time.time() >= _gemini_backoff_until


def _trip_gemini_backoff(error_message: str) -> None:
    global _gemini_backoff_until
    lower_msg = (error_message or "").lower()
    if "429" in lower_msg or "quota" in lower_msg or "rate limit" in lower_msg:
        _gemini_backoff_until = time.time() + GEMINI_BACKOFF_SECONDS
        logger.warning(f"Gemini backoff engaged for {GEMINI_BACKOFF_SECONDS}s due to error: {error_message}")


def _parse_model_chain(value: str, default: List[str]) -> List[str]:
    if value:
        return [model.strip() for model in value.split(",") if model.strip()]
    return default


DISPATCH_MODEL_CHAIN = _parse_model_chain(
    os.getenv("DISPATCH_MODELS"),
    ["models/gemini-2.5-flash", "models/gemini-1.5-flash", "models/gemini-lite"],
)
RESOURCE_MODEL_CHAIN = _parse_model_chain(
    os.getenv("RESOURCE_MODELS"),
    ["models/gemini-2.5-pro", "models/gemini-1.5-pro", "models/gemini-1.5-flash"],
)
SUMMARY_MODEL_CHAIN = _parse_model_chain(
    os.getenv("SUMMARY_MODELS"),
    ["models/gemini-2.5-flash", "models/gemini-1.5-flash", "models/gemini-lite"],
)


def _run_gemini(prompt: str, model_chain: List[str]) -> str:
    if not _gemini_available():
        return "[Gemini disabled]"
    last_error = ""
    for model_name in model_chain:
        try:
            genai.configure(api_key=GOOGLE_API_KEY)
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            text = getattr(response, "text", None)
            if not text and hasattr(response, "candidates"):
                candidates = response.candidates or []
                if candidates and candidates[0].content.parts:
                    text = "".join(part.text for part in candidates[0].content.parts if hasattr(part, "text"))
            if not text:
                text = ""
            return text.strip()
        except Exception as e:
            last_error = str(e)
            logger.error(f"Gemini API error ({model_name}): {e}")
            _trip_gemini_backoff(last_error)
    return f"[Gemini error: {last_error or 'unavailable'}]"

# --- A2A Message Envelope ---
class MessageEnvelope:
    def __init__(self, content=None, sender=None, receiver=None, trace=None, context=None):
        self.content = content or {}
        self.sender = sender
        self.receiver = receiver
        self.trace = trace or []  # List of (agent, message) tuples
        self.context = context or {}

    def add_trace(self, agent, message):
        self.trace.append({"agent": agent, "message": message})

    def to_dict(self):
        return {
            "content": self.content,
            "sender": self.sender,
            "receiver": self.receiver,
            "trace": self.trace,
            "context": self.context
        }

# --- Session and Memory Management ---
class Session:
    def __init__(self, session_id=None):
        self.session_id = session_id or str(uuid.uuid4())
        self.history = []  # List of (user, agent) tuples

    def add_turn(self, user_msg, agent_msg):
        self.history.append((user_msg, agent_msg))

class Memory:
    def __init__(self):
        self.knowledge = []  # List of facts, summaries, etc.

    def add_fact(self, fact):
        self.knowledge.append(fact)

# --- Observability (Logging, Tracing, Metrics) ---
def log_event(event: str, data: dict = None):
    logger.info(f"EVENT: {event} | DATA: {data}")


# --- Concise Display Summary Agent ---

class SummaryAgent:
    def __init__(self, name="Summary-Agent"):
        self.name = name

    def handle_envelope(self, envelope, session: Session = None):
        # Accepts MessageEnvelope, adds display_summary
        content = envelope.content
        summary = content.get('summary', '')
        recommendation = content.get('recommendation', '')
        urgency = content.get('urgency', 'CRITICAL')
        incident = content.get('incident', {})
        display_summary = self.summarize_for_display(summary, recommendation, urgency, incident)
        content['display_summary'] = display_summary
        envelope.add_trace(self.name, {'display_summary': display_summary})
        envelope.content = content
        return envelope

    def summarize_for_display(self, summary, recommendation, urgency, incident):
        prompt = (
            f"You are a UI assistant for a tiny dispatch terminal. "
            f"Given this summary: {summary}\n"
            f"and this recommendation: {recommendation}\n"
            f"and this urgency: {urgency}\n"
            f"Generate a concise, plain-language alert (max 60 chars) for a small screen. "
            f"Do not include JSON, just the message."
        )
        response_text = _run_gemini(prompt, SUMMARY_MODEL_CHAIN)
        if response_text.startswith("[Gemini"):
            return format_display_alert(summary, recommendation, incident, urgency)
        return response_text.strip()

def get_summary_agent():
    return SummaryAgent()

# --- Agent Definitions ---

class DispatchAgent:
    def __init__(self, name, tools, memory=None):
        self.name = name
        self.tools = tools
        self.memory = memory or Memory()

    def handle_envelope(self, envelope, session: Session = None):
        # Accepts MessageEnvelope, adds summary and recommendation
        incident = envelope.content.get('incident', envelope.content)
        plan = self._plan_dispatch(incident)
        log_event("handle_incident", {"incident": incident, "summary": plan['summary'], "recommendation": plan['recommendation']})
        self.memory.add_fact({"incident": incident, "summary": plan['summary']})
        if session:
            session.add_turn(str(incident), plan['recommendation'])
        envelope.content['incident'] = incident
        envelope.content['summary'] = plan['summary']
        envelope.content['recommendation'] = plan['recommendation']
        envelope.add_trace(self.name, {'summary': plan['summary'], 'recommendation': plan['recommendation']})
        return envelope

    def handle_incident(self, incident: Dict[str, Any], session: Session = None) -> Dict[str, Any]:
        envelope = MessageEnvelope(content={"incident": incident}, sender=self.name, receiver=None)
        envelope = self.handle_envelope(envelope, session=session)
        return envelope.content

    def _plan_dispatch(self, incident: Dict[str, Any]) -> Dict[str, Any]:
        prompt = (
            f"You are a dispatch agent. Given this incident: {incident}, "
            f"summarize the situation and recommend the best unit to deploy. "
            f"Respond with a JSON object with 'summary' and 'recommendation'."
        )
        llm_response = self.ask_gemini(prompt)
        import json
        plan = {"summary": "", "recommendation": ""}
        try:
            result = json.loads(llm_response)
            plan["summary"] = result.get('summary', '')
            plan["recommendation"] = result.get('recommendation', '')
        except Exception:
            plan["summary"] = llm_response
            plan["recommendation"] = llm_response

        if not plan["summary"] or plan["summary"].startswith("[Gemini"):
            fallback = plan_relief_response(incident)
            plan["summary"] = fallback["summary"]
            plan["recommendation"] = fallback["recommendation"]
        return plan

    def ask_gemini(self, prompt: str) -> str:
        return _run_gemini(prompt, DISPATCH_MODEL_CHAIN)

# --- Specialized Agent: ResourceAgent ---

class ResourceAgent:
    def __init__(self, name="Resource-Agent", memory=None):
        self.name = name
        self.memory = memory or Memory()

    def handle_envelope(self, envelope, session: Session = None):
        # Accepts MessageEnvelope, adds resources and resource_summary
        incident = envelope.content.get('incident', envelope.content)
        prompt = (
            f"You are a resource allocation agent. Given this incident: {incident}, "
            f"list the best resources or units to send. "
            f"Respond with a JSON object with a 'resources' list and a 'summary' string."
        )
        llm_response = self.ask_gemini(prompt)
        import json
        try:
            result = json.loads(llm_response)
            resources = result.get('resources', [])
            resource_summary = result.get('summary', '')
        except Exception:
            resources = []
            resource_summary = llm_response

        if not resources or (isinstance(resources, str) and resources.startswith("[Gemini")):
            fallback = plan_relief_response(incident)
            resources = fallback["resources"]
            resource_summary = fallback["resource_summary"]

        log_event("resource_allocation", {"incident": incident, "resources": resources})
        self.memory.add_fact({"incident": incident, "resources": resources})
        if session:
            session.add_turn(str(incident), resource_summary)
        envelope.content['resources'] = resources
        envelope.content['resource_summary'] = resource_summary
        envelope.add_trace(self.name, {'resources': resources, 'resource_summary': resource_summary})
        return envelope

    def handle_incident(self, incident: Dict[str, Any], session: Session = None) -> Dict[str, Any]:
        envelope = MessageEnvelope(content={"incident": incident}, sender=self.name, receiver=None)
        envelope = self.handle_envelope(envelope, session=session)
        return envelope.content

    def ask_gemini(self, prompt: str) -> str:
        return _run_gemini(prompt, RESOURCE_MODEL_CHAIN)

def get_resource_agent():
    return ResourceAgent()

def get_dispatch_agent():
    return DispatchAgent(
        name="ResQ-Agent",
        tools=[get_available_units, notify_dispatch]
    )

def get_multiagent_system():
    agent1 = get_dispatch_agent()
    resource_agent = get_resource_agent()
    return MultiAgentSystem([agent1, resource_agent])

class MultiAgentSystem:
    def __init__(self, agents: List[Any]):
        self.agents = agents

    def orchestrate(self, incident: Dict[str, Any], session: Session = None):
        envelope = MessageEnvelope(content={"incident": incident}, sender="user", receiver=None)
        for agent in self.agents:
            envelope = agent.handle_envelope(envelope, session=session)
        return envelope.content

# --- Advanced A2A Orchestrator ---
class A2AOrchestrator:
    def __init__(self, agents: List[Any]):
        self.agents = agents

    def orchestrate(self, envelope: MessageEnvelope, session: Session = None):
        # Each agent receives and returns a MessageEnvelope
        for agent in self.agents:
            envelope.sender = envelope.receiver
            envelope.receiver = agent.name
            envelope = agent.handle_envelope(envelope, session=session)
        return envelope

def get_a2a_orchestrator():
    agent1 = get_dispatch_agent()
    resource_agent = get_resource_agent()
    summary_agent = get_summary_agent()
    decision_agent = get_decision_agent()
    return A2AOrchestrator([agent1, resource_agent, summary_agent, decision_agent])
