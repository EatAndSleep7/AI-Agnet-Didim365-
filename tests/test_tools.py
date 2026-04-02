import json
from unittest.mock import patch, MagicMock


# ── get_customer_raw_data ────────────────────────────────────────────────────

def test_get_customer_raw_data_found(db_conn):
    """유효한 고객번호로 3개 테이블 데이터 반환"""
    from app.agents.tools import get_customer_raw_data
    row = db_conn.execute("SELECT customer_id FROM customer_basic LIMIT 1").fetchone()
    assert row, "banking.db에 customer_basic 데이터가 없습니다"

    result = json.loads(get_customer_raw_data.invoke(row["customer_id"]))
    assert "basic" in result
    assert "profile" in result
    assert "consultations" in result


def test_get_customer_raw_data_not_found():
    """존재하지 않는 고객번호 → found: False"""
    from app.agents.tools import get_customer_raw_data
    result = json.loads(get_customer_raw_data.invoke("CUST_INVALID"))
    assert result.get("found") is False
    assert "message" in result


# ── get_banker_dashboard ─────────────────────────────────────────────────────

def test_get_banker_dashboard_found(db_conn):
    """유효한 직원번호로 점수 반환"""
    from app.agents.tools import get_banker_dashboard
    row = db_conn.execute("SELECT employee_id FROM best_banker_status LIMIT 1").fetchone()
    assert row, "banking.db에 best_banker_status 데이터가 없습니다"

    result = json.loads(get_banker_dashboard.invoke(row["employee_id"]))
    assert result.get("found") is True
    assert "deposit_score" in result


def test_get_banker_dashboard_not_found():
    """존재하지 않는 직원번호 → found: False"""
    from app.agents.tools import get_banker_dashboard
    result = json.loads(get_banker_dashboard.invoke("EMP_INVALID"))
    assert result.get("found") is False
    assert "message" in result


# ── get_group_statistics ─────────────────────────────────────────────────────

def test_get_group_statistics_structure():
    """4개 카테고리 × 3개 키 구조 반환"""
    from app.agents.tools import get_group_statistics
    result = json.loads(get_group_statistics.invoke({}))
    expected_categories = {"수신", "개인여신", "기업여신", "디지털금융"}
    assert set(result.keys()) == expected_categories
    for cat, info in result.items():
        assert "top10_score" in info, f"{cat} top10_score 누락"
        assert "median_score" in info, f"{cat} median_score 누락"
        assert "total_members" in info, f"{cat} total_members 누락"


def test_get_group_statistics_top10_edge_case():
    """직원 수가 10명 미만이어도 top10_score가 반환됨 (index [-1] fallback)"""
    from app.agents.tools import get_group_statistics
    result = json.loads(get_group_statistics.invoke({}))
    for cat, info in result.items():
        assert isinstance(info["top10_score"], (int, float)), f"{cat} top10_score 타입 오류"


# ── get_worst_group ──────────────────────────────────────────────────────────

def test_get_worst_group_returns_valid_category(db_conn):
    """직원의 worst_category가 유효한 카테고리명 반환"""
    from app.agents.tools import get_worst_group
    row = db_conn.execute("SELECT employee_id FROM best_banker_status LIMIT 1").fetchone()
    assert row

    result = json.loads(get_worst_group.invoke(row["employee_id"]))
    assert "worst_category" in result
    assert result["worst_category"] in {"수신", "개인여신", "기업여신", "디지털금융"}
    assert "gap_to_top10" in result


# ── get_top_product_for_customer ─────────────────────────────────────────────

def test_get_top_product_for_customer_no_category(db_conn):
    """category 없이 호출 시 최고 점수 상품 반환"""
    from app.agents.tools import get_top_product_for_customer
    row = db_conn.execute("SELECT customer_id FROM product_recommendation LIMIT 1").fetchone()
    assert row

    result = json.loads(get_top_product_for_customer.invoke(row["customer_id"]))
    assert result.get("found") is True
    assert "product_name" in result


def test_get_top_product_for_customer_with_category(db_conn):
    """category 파라미터 지정 시 해당 카테고리만 필터링"""
    from app.agents.tools import get_top_product_for_customer
    row = db_conn.execute(
        "SELECT customer_id, category FROM product_recommendation LIMIT 1"
    ).fetchone()
    assert row

    result = json.loads(get_top_product_for_customer.invoke({
        "customer_id": row["customer_id"],
        "category": row["category"],
    }))
    if result.get("found"):
        assert result["category"] == row["category"]


# ── get_most_pushed_product_in_group ─────────────────────────────────────────

def test_get_most_pushed_product_string_input():
    """단일 문자열 customer_ids 전달 시 크래시 없이 처리"""
    from app.agents.tools import get_most_pushed_product_in_group
    # 문자열을 전달해도 내부에서 리스트로 변환되어야 함
    result = json.loads(get_most_pushed_product_in_group.invoke({
        "customer_ids": "CUST001",
        "category": "수신",
    }))
    assert "found" in result


def test_get_most_pushed_product_empty_list():
    """빈 리스트 전달 시 found: False 반환"""
    from app.agents.tools import get_most_pushed_product_in_group
    result = json.loads(get_most_pushed_product_in_group.invoke({
        "customer_ids": [],
        "category": "수신",
    }))
    assert result.get("found") is False


# ── summarize_customer (LLM 모킹) ────────────────────────────────────────────

def test_summarize_customer_not_found():
    """존재하지 않는 고객번호 → 에러 메시지 문자열 반환 (LLM 호출 없음)"""
    from app.agents.tools import summarize_customer
    result = summarize_customer.invoke("CUST_INVALID")
    assert isinstance(result, str)
    assert len(result) > 0


def test_summarize_customer_calls_llm(db_conn):
    """유효한 고객번호 → LLM chain.invoke 호출 후 문자열 반환"""
    from app.agents.tools import summarize_customer

    row = db_conn.execute("SELECT customer_id FROM customer_basic LIMIT 1").fetchone()
    assert row

    expected = "예금 잔액이 높은 40대 기혼 고객으로 마케팅 동의 완료."
    mock_chain = MagicMock()
    mock_chain.invoke.return_value = expected

    # prompt | llm | parser 체인 전체를 `mock_chain`으로 대체
    with patch("langchain_core.prompts.ChatPromptTemplate.from_messages") as mock_from_msg:
        mock_prompt = MagicMock()
        mock_from_msg.return_value = mock_prompt
        mock_prompt.__or__ = MagicMock(return_value=mock_chain)
        mock_chain.__or__ = MagicMock(return_value=mock_chain)

        result = summarize_customer.invoke(row["customer_id"])

    assert result == expected
