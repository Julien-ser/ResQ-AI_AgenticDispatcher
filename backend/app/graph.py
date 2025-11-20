"""
Graph orchestration for multi-agent workflows.
"""


"""
Defines the workflow graph for multi-agent orchestration (sequential pattern).
"""


"""
Defines the workflow graph for multi-agent orchestration (sequential pattern).
"""

def build_dispatch_graph():
    """Return a simple workflow graph for dispatch orchestration (sequential pipeline)."""
    return {
        'nodes': ['Incident Intake', 'Triage', 'Dispatch'],
        'edges': [('Incident Intake', 'Triage'), ('Triage', 'Dispatch')]
    }
