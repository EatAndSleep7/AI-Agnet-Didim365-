# tests/test_recommendation_routing.py
import pytest
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage


# ── _extract_customer_id ──────────────────────────────────────────────────────

def test_extract_customer_id_from_human_message():
    from app.agents.recommendation_agent import _extract_customer_id
    msgs = [HumanMessage(content="CUST001 고객 추천해줘")]
    assert _extract_customer_id(msgs) == "CUST001"


def test_extract_customer_id_returns_most_recent():
    from app.agents.recommendation_agent import _extract_customer_id
    msgs = [
        HumanMessage(content="CUST003 정보 조회"),
        HumanMessage(content="CUST007도 있어"),
    ]
    assert _extract_customer_id(msgs) == "CUST007"


def test_extract_customer_id_none_when_absent():
    from app.agents.recommendation_agent import _extract_customer_id
    msgs = [HumanMessage(content="추천해줘")]
    assert _extract_customer_id(msgs) is None


def test_extract_customer_id_ignores_emp():
    from app.agents.recommendation_agent import _extract_customer_id
    msgs = [HumanMessage(content="EMP001 직원 추천해줘")]
    assert _extract_customer_id(msgs) is None


# ── _extract_explicit_category ────────────────────────────────────────────────

def test_extract_explicit_category_기업여신():
    from app.agents.recommendation_agent import _extract_explicit_category
    msgs = [HumanMessage(content="기업여신 올리려면 어떻게 해?")]
    assert _extract_explicit_category(msgs) == "기업여신"


def test_extract_explicit_category_디지털():
    from app.agents.recommendation_agent import _extract_explicit_category
    msgs = [HumanMessage(content="디지털 점수 높이고 싶어")]
    assert _extract_explicit_category(msgs) == "디지털금융"


def test_extract_explicit_category_전자금융():
    from app.agents.recommendation_agent import _extract_explicit_category
    msgs = [HumanMessage(content="전자금융 실적 올리고 싶어")]
    assert _extract_explicit_category(msgs) == "디지털금융"


def test_extract_explicit_category_여신_maps_to_개인여신():
    from app.agents.recommendation_agent import _extract_explicit_category
    msgs = [HumanMessage(content="여신 추천 부탁해")]
    assert _extract_explicit_category(msgs) == "개인여신"


def test_extract_explicit_category_기업여신_takes_priority_over_여신():
    from app.agents.recommendation_agent import _extract_explicit_category
    msgs = [HumanMessage(content="기업여신 올리려면")]
    assert _extract_explicit_category(msgs) == "기업여신"


def test_extract_explicit_category_none_when_absent():
    from app.agents.recommendation_agent import _extract_explicit_category
    msgs = [HumanMessage(content="추천 부탁해")]
    assert _extract_explicit_category(msgs) is None


# ── create_recommendation_agent smoke test ────────────────────────────────────

def test_create_recommendation_agent_returns_compiled_graph():
    """인터페이스 변경 없이 컴파일된 그래프를 반환하는지 확인"""
    from unittest.mock import MagicMock
    from app.agents.recommendation_agent import create_recommendation_agent
    mock_model = MagicMock()
    graph = create_recommendation_agent(mock_model, checkpointer=None)
    assert hasattr(graph, "invoke")
    assert hasattr(graph, "astream")
