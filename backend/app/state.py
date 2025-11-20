"""
State management for ResQ-AI Dispatch System.
Handles session, memory, and incident tracking.
"""

import uuid
from datetime import datetime

# Agentic state: session, memory, incident tracking, metrics
from app.agents import Session, Memory


class SystemState:
    def __init__(self):
        self.active_incidents = []
        self.memory = Memory()
        self.sessions = {}  # session_id -> Session
        self.metrics = {"incidents": 0, "decisions": 0}

    def add_incident(self, incident):
        record = dict(incident)
        record.setdefault("id", str(uuid.uuid4()))
        record.setdefault("timestamp", datetime.utcnow().isoformat())
        self.active_incidents.append(record)
        self.metrics["incidents"] += 1
        return record

    def resolve_incident(self, incident_id):
        self.active_incidents = [i for i in self.active_incidents if i.get('id') != incident_id]

    def get_or_create_session(self, session_id=None):
        if session_id and session_id in self.sessions:
            return self.sessions[session_id]
        session = Session(session_id)
        self.sessions[session.session_id] = session
        return session
