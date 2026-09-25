from app.focus import decide_focus
from app.schemas import FocusDecisionRequest, ToolDef
from app.selector import FakeSelector


def test_valid_focus_returns_full_bundle():
    selector = FakeSelector(choice_id="implement")
    request = FocusDecisionRequest(
        task_id="t1",
        session_id="s1",
        available_tools=[ToolDef(name="read_file"), ToolDef(name="write_file"), ToolDef(name="grep")],
    )

    response, record = decide_focus(request, selector)

    assert response.focus == "implement"
    assert set(response.tools) == {"read_file", "write_file", "grep"}
    assert response.fallback_used is False
    assert record.final_choice == "implement"


def test_answer_focus_gets_no_tools():
    selector = FakeSelector(choice_id="answer")
    request = FocusDecisionRequest(task_id="t2", session_id="s2")

    response, record = decide_focus(request, selector)

    assert response.focus == "answer"
    assert response.tools == []


def test_stale_tool_is_filtered_out():
    selector = FakeSelector(choice_id="verify")
    # host only currently knows about run_tests; read_file was removed/renamed
    request = FocusDecisionRequest(
        task_id="t3",
        session_id="s3",
        available_tools=[ToolDef(name="run_tests")],
    )

    response, record = decide_focus(request, selector)

    assert response.tools == ["run_tests"]


def test_abstain_falls_back_to_inspect():
    selector = FakeSelector(abstain=True)
    request = FocusDecisionRequest(task_id="t4", session_id="s4")

    response, record = decide_focus(request, selector)

    assert response.focus == "inspect"
    assert response.fallback_used is True
    assert record.fallback_used is True
