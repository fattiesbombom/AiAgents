"""LangGraph workflow definition for the security incident response system."""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send

from backend.workflow.state import VIDEO_ROUTE_SOURCE_TYPES, IncidentState
from backend.workflow.nodes.cc_officer import cc_officer
from backend.workflow.nodes.confirmation_check import confirmation_check
from backend.workflow.nodes.human_review import human_review
from backend.workflow.nodes.logs_agent import logs_agent
from backend.workflow.nodes.output_writer import output_writer
from backend.workflow.nodes.police_escalation import police_escalation
from backend.workflow.nodes.routine_task import routine_task
from backend.workflow.nodes.police_immediate import police_immediate
from backend.workflow.nodes.risk_decision import risk_decision
from backend.workflow.nodes.sop_retrieval import sop_retrieval
from backend.workflow.nodes.supervisor import supervisor
from backend.workflow.nodes.vision_agent import vision_agent


def entry_router(state: IncidentState) -> Literal["routine_task", "supervisor"]:
    if state.get("task_mode") == "routine":
        return "routine_task"
    return "supervisor"


def routine_exit_router(state: IncidentState) -> Literal["supervisor", "output_writer"]:
    if state.get("task_mode") == "non_routine":
        return "supervisor"
    return "output_writer"


def post_supervisor_router(
    state: IncidentState,
) -> Literal["sop_retrieval", "vision_agent", "logs_agent"]:
    """After supervisor: officer_down → SOP (skip vision/logs/confirmation); video sources → vision; else logs."""
    if state.get("incident_type") == "officer_down":
        return "sop_retrieval"
    if state["source_type"] in VIDEO_ROUTE_SOURCE_TYPES:
        return "vision_agent"
    return "logs_agent"


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


def post_risk_router(
    state: IncidentState,
) -> Literal["cc_officer", "human_review", "output_writer", "police_immediate"]:
    """After risk_decision: officer_down → immediate police; CC remote; else human review or output."""
    if state.get("incident_type") == "officer_down":
        return "police_immediate"
    if state["feed_source"] == "remote" and state.get("deployment_type") == "command_centre":
        return "cc_officer"
    if state["feed_source"] == "remote":
        return "human_review"
    return "output_writer"


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
    graph.add_node("routine_task", routine_task)
    graph.add_node("supervisor", supervisor)
    graph.add_node("vision_agent", vision_agent)
    graph.add_node("logs_agent", logs_agent)
    graph.add_node("confirmation_check", confirmation_check)
    graph.add_node("sop_retrieval", sop_retrieval)
    graph.add_node("risk_decision", risk_decision)
    graph.add_node("cc_officer", cc_officer)
    graph.add_node("human_review", human_review)
    graph.add_node("police_immediate", police_immediate)
    graph.add_node("police_escalation", police_escalation)
    graph.add_node("output_writer", output_writer)

    # Entry: routine tasks vs full incident pipeline
    graph.add_conditional_edges(
        START,
        entry_router,
        {"routine_task": "routine_task", "supervisor": "supervisor"},
    )

    graph.add_conditional_edges(
        "routine_task",
        routine_exit_router,
        {"supervisor": "supervisor", "output_writer": "output_writer"},
    )

    graph.add_conditional_edges(
        "supervisor",
        post_supervisor_router,
        {
            "sop_retrieval": "sop_retrieval",
            "vision_agent": "vision_agent",
            "logs_agent": "logs_agent",
        },
    )

    # vision/logs -> confirmation_check
    graph.add_edge("vision_agent", "confirmation_check")
    graph.add_edge("logs_agent", "confirmation_check")

    # confirmation_check conditional (parallel when live+confirmed)
    graph.add_conditional_edges("confirmation_check", _confirmation_router)

    # sop_retrieval -> risk_decision
    graph.add_edge("sop_retrieval", "risk_decision")

    graph.add_conditional_edges(
        "risk_decision",
        post_risk_router,
        {
            "police_immediate": "police_immediate",
            "cc_officer": "cc_officer",
            "human_review": "human_review",
            "output_writer": "output_writer",
        },
    )

    graph.add_edge("cc_officer", "human_review")

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
