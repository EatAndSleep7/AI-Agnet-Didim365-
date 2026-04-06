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



# ── create_recommendation_agent smoke test ────────────────────────────────────

def test_create_recommendation_agent_returns_compiled_graph():
    """인터페이스 변경 없이 컴파일된 그래프를 반환하는지 확인"""
    from unittest.mock import MagicMock
    from app.agents.recommendation_agent import create_recommendation_agent
    mock_model = MagicMock()
    graph = create_recommendation_agent(mock_model, checkpointer=None)
    assert hasattr(graph, "invoke")
    assert hasattr(graph, "astream")
