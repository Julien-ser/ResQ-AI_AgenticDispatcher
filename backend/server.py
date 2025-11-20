# Endpoint to display all active incidents
"""
FastAPI server for ResQ-AI Dispatch System.
Handles REST API and WebSocket connections to hardware client.
"""

import os
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.state import SystemState
from app.agents import get_dispatch_agent, get_decision_agent, get_multiagent_system, log_event, get_summary_agent, get_a2a_orchestrator, MessageEnvelope
from app.relief_tools import get_available_units, notify_dispatch

# Load environment variables (API keys, etc.)
from dotenv import load_dotenv
load_dotenv()
#print("API_KEY from env:", os.getenv("API_KEY"))

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
state = SystemState()


agent = get_dispatch_agent()
multiagent = get_multiagent_system()
summary_agent = get_summary_agent()
a2a_orchestrator = get_a2a_orchestrator()
decision_agent = get_decision_agent()

# Endpoint for ESP32 to poll for latest incident (with session support, A2A)
@app.get('/incident/latest')
async def get_latest_incident(session_id: str = None):
    if state.active_incidents:
        incident = state.active_incidents[-1]
        session = state.get_or_create_session(session_id)
        envelope = MessageEnvelope(content={"incident": incident, "urgency": incident.get("urgency", "CRITICAL")}, sender="user", receiver=None)
        envelope = a2a_orchestrator.orchestrate(envelope, session=session)
        content = envelope.content
        log_event("incident_polled", {"incident": incident, "session_id": session.session_id, "trace": envelope.trace})
        return JSONResponse({
            'summary': content.get('summary', ''),
            'recommendation': content.get('recommendation', ''),
            'urgency': content.get('urgency', 'CRITICAL'),
            'id': incident.get('id', None),
            'session_id': session.session_id,
            'display_summary': content.get('display_summary', ''),
            'resources': content.get('resources', []),
            'resource_summary': content.get('resource_summary', ''),
            'trace': envelope.trace
        })
    return JSONResponse({'active': False})

@app.get('/incidents')
async def get_all_incidents():
    return {"active_incidents": state.active_incidents}


# ESP32 sends decision (SEND/HOLD) -- now uses A2A orchestrator for full agentic trace
@app.post('/incident/decision')
async def incident_decision(request: Request):
    data = await request.json()
    action = data.get('action')
    session_id = data.get('session_id')
    log_event("incident_decision", {"action": action, "session_id": session_id})
    state.metrics["decisions"] += 1

    incident_id = None
    if state.active_incidents:
        incident = state.active_incidents[-1]
        incident_id = incident.get('id', None)
        # Remove the latest incident after a decision
        if 'id' in incident:
            state.resolve_incident(incident['id'])
        else:
            state.active_incidents.pop()  # fallback if no id

    # Use A2A orchestrator to process the decision as an agentic step
    session = state.get_or_create_session(session_id)
    envelope = MessageEnvelope(
        content={
            "action": action,
            "incident_id": incident_id
        },
        sender="user",
        receiver=None
    )
    envelope = a2a_orchestrator.orchestrate(envelope, session=session)
    log_event("decision_processed", {"action": action, "incident_id": incident_id, "trace": envelope.trace})
    # Return the final envelope content and trace
    return {
        "decision_status": envelope.content.get("decision_status", ""),
        "decision_message": envelope.content.get("decision_message", ""),
        "incident_id": incident_id,
        "trace": envelope.trace
    }

@app.get('/decision/history')
async def get_decision_history():
    return {"history": decision_agent.get_history()}

# Endpoint to add a new incident (A2A orchestrator, advanced agentic pipeline)
@app.post('/incident')
async def new_incident(incident: dict, session_id: str = None):
    incident = state.add_incident(incident)
    session = state.get_or_create_session(session_id)
    # Use A2A orchestrator for advanced agentic pipeline
    envelope = MessageEnvelope(content={"incident": incident, "urgency": incident.get("urgency", "CRITICAL")}, sender="user", receiver=None)
    envelope = a2a_orchestrator.orchestrate(envelope, session=session)
    log_event("incident_added", {"incident": incident, "session_id": session.session_id, "trace": envelope.trace})
    # Optionally notify hardware client (WebSocket, etc.)
    return envelope.to_dict()


# WebSocket for real-time communication (optional, for future use)
@app.websocket('/ws')
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_text()
        log_event("websocket_message", {"data": data})
        await websocket.send_text(f"Echo: {data}")
