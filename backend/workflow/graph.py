"""LangGraph workflow definition for the security incident response system."""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, StateGraph
from langgraph.types import Command, Send

from backend.workflow.state import IncidentState
from backend.workflow.nodes.confirmation_check import confirmation_check
from backend.workflow.nodes.human_review import human_review
from backend.workflow.nodes.logs_agent import logs_agent
from backend.workflow.nodes.output_writer import output_writer
from backend.workflow.nodes.police_escalation import police_escalation
from backend.workflow.nodes.police_immediate import police_immediate
from backend.workflow.nodes.risk_decision import risk_decision
from backend.workflow.nodes.sop_retrieval import sop_retrieval
from backend.workflow.nodes.supervisor import supervisor
from backend.workflow.nodes.vision_agent import vision_agent


def _route_source_type(state: IncidentState) -> Literal["vision_agent", "logs_agent"]:
    return "vision_agent" if state["source_type"] == "video" else "logs_agent"


async def _confirmation_router(state: IncidentState) -> Command:
    """Route after confirmation_check.

    If confirmed and live, run police_immediate and sop_retrieval in parallel.
    Otherwise continue to sop_retrieval only.
    """
    confirmed = bool(state.get("confirmed"))
    feed_source = state.get("feed_source")
    if confirmed and feed_source == "live":
        return Command(goto=[Send("police_immediate", state), Send("sop_retrieval", state)])
    return Command(goto="sop_retrieval")


def _route_feed_source(state: IncidentState) -> Literal["output_writer", "human_review"]:
    return "human_review" if state["feed_source"] == "remote" else "output_writer"


def _route_human_review(
    state: IncidentState,
) -> Literal["police_escalation", "output_writer", "human_review"]:
    status = state.get("human_review_status")
    if status == "approved":
        return "police_escalation"
    if status == "rejected":
        state["incident_status"] = "rejected"
        return "output_writer"
    # pending -> stay at human_review (interrupt will pause before running again)
    return "human_review"


def build_graph():
    graph = StateGraph(IncidentState)

    # Nodes
    graph.add_node("supervisor", supervisor)
    graph.add_node("vision_agent", vision_agent)
    graph.add_node("logs_agent", logs_agent)
    graph.add_node("confirmation_check", confirmation_check)
    graph.add_node("sop_retrieval", sop_retrieval)
    graph.add_node("risk_decision", risk_decision)
    graph.add_node("human_review", human_review)
    graph.add_node("police_immediate", police_immediate)
    graph.add_node("police_escalation", police_escalation)
    graph.add_node("output_writer", output_writer)

    # Entry
    graph.set_entry_point("supervisor")

    # supervisor -> source_type_router (conditional)
    graph.add_conditional_edges("supervisor", _route_source_type)

    # vision/logs -> confirmation_check
    graph.add_edge("vision_agent", "confirmation_check")
    graph.add_edge("logs_agent", "confirmation_check")

    # confirmation_check conditional (parallel when live+confirmed)
    graph.add_conditional_edges("confirmation_check", _confirmation_router)

    # sop_retrieval -> risk_decision
    graph.add_edge("sop_retrieval", "risk_decision")

    # risk_decision -> feed_source_check (conditional)
    graph.add_conditional_edges("risk_decision", _route_feed_source)

    # human_review conditional outcomes
    graph.add_conditional_edges("human_review", _route_human_review)

    # police nodes -> output_writer
    graph.add_edge("police_immediate", "output_writer")
    graph.add_edge("police_escalation", "output_writer")

    # output_writer -> END
    graph.add_edge("output_writer", END)

    return graph.compile(interrupt_before=["human_review"])


workflow = build_graph()


async def run_workflow(state: IncidentState) -> IncidentState:
    """Run the workflow asynchronously."""
    return await workflow.ainvoke(state)
