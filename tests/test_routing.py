from app.routing import decide_route
from app.schemas import RouteCandidate, RouteDecisionRequest
from app.selector import FakeSelector


def make_candidates():
    return [
        RouteCandidate(id="gemini-flash", provider="vertex", model="gemini-2.5-flash"),
        RouteCandidate(id="gemini-pro", provider="vertex", model="gemini-2.5-pro"),
    ]


def test_pinned_route_bypasses_selector():
    selector = FakeSelector(abstain=True)  # should never be consulted
    request = RouteDecisionRequest(task_id="t1", candidates=make_candidates(), pinned_route_id="gemini-pro")

    response, record = decide_route(request, selector)

    assert response.decision == "pinned"
    assert response.chosen.id == "gemini-pro"
    assert record.final_choice == "gemini-pro"


def test_valid_selection_is_accepted():
    selector = FakeSelector(choice_id="gemini-flash")
    request = RouteDecisionRequest(task_id="t2", candidates=make_candidates())

    response, record = decide_route(request, selector)

    assert response.decision == "selected"
    assert response.chosen.id == "gemini-flash"
    assert response.fallback_used is False
    assert record.validated is True


def test_selector_choosing_unknown_id_falls_back():
    selector = FakeSelector(choice_id="not-a-real-candidate")
    request = RouteDecisionRequest(
        task_id="t3",
        candidates=make_candidates(),
        fallback_route_id="gemini-flash",
    )

    response, record = decide_route(request, selector)

    assert response.decision == "fallback"
    assert response.fallback_used is True
    assert response.chosen.id == "gemini-flash"
    assert record.fallback_used is True


def test_abstain_without_fallback_route_is_abstained():
    selector = FakeSelector(abstain=True)
    request = RouteDecisionRequest(task_id="t4", candidates=make_candidates())

    response, record = decide_route(request, selector)

    assert response.decision == "abstained"
    assert response.chosen is None
    assert record.abstained is True
