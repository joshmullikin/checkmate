"""Tests for agent/graph.py routing functions."""
import pytest

from agent.graph import route_intent, should_execute_or_clarify, should_continue_execution


# ---------------------------------------------------------------------------
# route_intent
# ---------------------------------------------------------------------------

def test_route_intent_generate_test_cases():
    state = {"intent": "generate_test_cases"}
    assert route_intent(state) == "generator"


def test_route_intent_execute_test():
    state = {"intent": "execute_test"}
    assert route_intent(state) == "planner"


def test_route_intent_analyze_results():
    state = {"intent": "analyze_results"}
    assert route_intent(state) == "reporter"


def test_route_intent_unknown_defaults_to_planner():
    state = {"intent": "manage_project"}
    assert route_intent(state) == "planner"


def test_route_intent_missing_intent_defaults_to_planner():
    state = {}
    assert route_intent(state) == "planner"


# ---------------------------------------------------------------------------
# should_execute_or_clarify
# ---------------------------------------------------------------------------

def test_should_execute_or_clarify_no_placeholders():
    state = {
        "test_plan": {
            "steps": [
                {"action": "click", "target": "Submit button", "value": None, "description": "Click submit"},
            ]
        }
    }
    assert should_execute_or_clarify(state) == "executor"


def test_should_execute_or_clarify_placeholder_in_target():
    state = {
        "test_plan": {
            "steps": [
                {"action": "click", "target": "{BUTTON_NAME}", "value": None, "description": "Click"},
            ]
        }
    }
    assert should_execute_or_clarify(state) == "end"


def test_should_execute_or_clarify_placeholder_in_value():
    state = {
        "test_plan": {
            "steps": [
                {"action": "fill", "target": "input", "value": "{EMAIL}", "description": "Fill email"},
            ]
        }
    }
    assert should_execute_or_clarify(state) == "end"


def test_should_execute_or_clarify_placeholder_in_description():
    state = {
        "test_plan": {
            "steps": [
                {"action": "navigate", "target": None, "value": None, "description": "Go to {URL}"},
            ]
        }
    }
    assert should_execute_or_clarify(state) == "end"


def test_should_execute_or_clarify_empty_steps():
    state = {"test_plan": {"steps": []}}
    assert should_execute_or_clarify(state) == "executor"


def test_should_execute_or_clarify_missing_test_plan():
    state = {}
    assert should_execute_or_clarify(state) == "executor"


# ---------------------------------------------------------------------------
# should_continue_execution
# ---------------------------------------------------------------------------

def test_should_continue_execution_more_steps():
    state = {
        "test_plan": {"steps": [{"action": "click"}, {"action": "fill"}]},
        "current_step": 1,
    }
    assert should_continue_execution(state) == "executor"


def test_should_continue_execution_at_last_step():
    state = {
        "test_plan": {"steps": [{"action": "click"}]},
        "current_step": 1,
    }
    assert should_continue_execution(state) == "reporter"


def test_should_continue_execution_no_test_plan():
    state = {"current_step": 0}
    assert should_continue_execution(state) == "reporter"


def test_should_continue_execution_current_step_zero():
    state = {
        "test_plan": {"steps": [{"action": "click"}, {"action": "fill"}]},
        "current_step": 0,
    }
    assert should_continue_execution(state) == "executor"
