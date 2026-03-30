from __future__ import annotations

import json
import os
import sqlite3
import statistics
from typing import Optional

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from elasticsearch import Elasticsearch
from langchain_elasticsearch import ElasticsearchRetriever
from langchain.tools import tool

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "banking.db")

GROUP_NAME = {1: "수신(예적금)", 2: "여신(대출)", 3: "전자금융"}
GROUP_COL = {1: "deposit_score", 2: "loan_score", 3: "digital_score"}


# ── DB 헬퍼 ───────────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ═══════════════════════════════════════════════════════════════════════════════
# Agent 1 · Agent 4 공통 — 고객 정보
# ═══════════════════════════════════════════════════════════════════════════════

@tool
def get_customer_raw_data(customer_id: str) -> str:
    """고객번호로 customer_basic, customer_profile, customer_consultation 3개 테이블을 조회하여 JSON 문자열로 반환합니다."""
    conn = _conn()
    c = conn.cursor()

    c.execute("SELECT * FROM customer_basic WHERE customer_id = ?", (customer_id,))
    basic = c.fetchone()
    if not basic:
        conn.close()
        return json.dumps({"error": f"고객번호 {customer_id}를 찾을 수 없습니다."}, ensure_ascii=False)

    c.execute("SELECT * FROM customer_profile WHERE customer_id = ?", (customer_id,))
    profile = c.fetchone()

    c.execute(
        "SELECT product_code, product_name, interaction_result, consulted_at "
        "FROM customer_consultation WHERE customer_id = ? ORDER BY consulted_at DESC",
        (customer_id,),
    )
    consultations = c.fetchall()
    conn.close()

    result = {
        "basic": dict(basic),
        "profile": dict(profile) if profile else {},
        "consultations": [dict(r) for r in consultations],
    }
    return json.dumps(result, ensure_ascii=False)


@tool
def summarize_customer(customer_id: str) -> str:
    """고객번호로 3개 테이블을 조회한 후 LLM으로 마케팅 관점의 한 문장 요약을 생성합니다. 다른 에이전트에서 고객 요약이 필요할 때도 이 tool을 사용하세요."""
    raw = get_customer_raw_data.invoke(customer_id)
    data = json.loads(raw)
    if "error" in data:
        return data["error"]

    from langchain_openai import ChatOpenAI
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser
    from app.core.config import settings
    from pydantic import SecretStr

    llm = ChatOpenAI(
        model=settings.OPENAI_MODEL,
        api_key=SecretStr(settings.OPENAI_API_KEY),
        temperature=0.3,
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "당신은 은행 마케팅 전문가입니다. "
         "고객의 기본정보(잔액, 서비스 가입, 마케팅 동의), 추정 라이프스타일, 최근 상담 이력을 종합하여 "
         "마케팅 관점에서 핵심만 담은 한 문장으로 고객을 요약하세요. "
         "단순 나열 금지. 마케팅 동의 여부와 상담 반응(1:긍정, 0:중립, -1:부정)을 반드시 반영하세요."),
        ("user", "고객번호: {customer_id}\n\n{data}\n\n위 정보를 한 문장으로 요약하세요."),
    ])
    chain = prompt | llm | StrOutputParser()
    summary = chain.invoke({"customer_id": customer_id, "data": json.dumps(data, ensure_ascii=False)})
    return summary


# ═══════════════════════════════════════════════════════════════════════════════
# Agent 2 · Agent 5 공통 — RAG
# ═══════════════════════════════════════════════════════════════════════════════

_retriever = None


def _bm25_query(q: str) -> dict:
    from app.core.config import settings
    return {
        "query": {"match": {settings.ES.CONTENT_FIELD: {"query": q, "operator": "or"}}},
        "size": settings.ES.TOP_K,
    }


def _build_retriever() -> ElasticsearchRetriever:
    from app.core.config import settings
    es_cfg = settings.ES
    es = Elasticsearch(
        es_cfg.URL,
        basic_auth=(es_cfg.USER, es_cfg.PASSWORD),
        verify_certs=False,
    )
    return ElasticsearchRetriever(
        index_name=es_cfg.INDEX,
        body_func=_bm25_query,
        content_field=es_cfg.CONTENT_FIELD,
        client=es,
    )


def _get_retriever() -> ElasticsearchRetriever:
    global _retriever
    if _retriever is None:
        _retriever = _build_retriever()
    return _retriever


@tool
def search_best_banker_regulations(query: str) -> str:
    """베스트뱅커 규정집(edu-collection)에서 질문과 관련된 내용을 BM25로 검색하여 반환합니다."""
    retriever = _get_retriever()
    docs = retriever.invoke(query)
    if not docs:
        return f"'{query}'에 대한 규정집 내용을 찾을 수 없습니다."
    parts = [f"[{i+1}] {doc.page_content[:600]}" for i, doc in enumerate(docs)]
    return "\n\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════════════
# Agent 3 · Agent 4 · Agent 5 공통 — 직원 현황
# ═══════════════════════════════════════════════════════════════════════════════

@tool
def get_banker_dashboard(employee_id: str) -> str:
    """직원번호로 best_banker_status를 조회하여 수신/여신/전자금융 점수와 합계를 JSON으로 반환합니다."""
    conn = _conn()
    c = conn.cursor()
    c.execute("SELECT * FROM best_banker_status WHERE employee_id = ?", (employee_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return json.dumps({"error": f"직원번호 {employee_id}를 찾을 수 없습니다."}, ensure_ascii=False)
    return json.dumps(dict(row), ensure_ascii=False)


@tool
def get_group_statistics() -> str:
    """best_banker_status 전체에서 수신/여신/전자금융 각 상품군의 10위 점수와 중앙값을 계산하여 JSON으로 반환합니다."""
    conn = _conn()
    c = conn.cursor()
    c.execute("SELECT deposit_score, loan_score, digital_score FROM best_banker_status ORDER BY employee_id")
    rows = c.fetchall()
    conn.close()

    result = {}
    for col, group_code in [("deposit_score", 1), ("loan_score", 2), ("digital_score", 3)]:
        scores = sorted([r[col] for r in rows], reverse=True)
        top10 = scores[9] if len(scores) >= 10 else scores[-1]
        mid = round(statistics.median(scores), 1)
        result[group_code] = {
            "group_name": GROUP_NAME[group_code],
            "top10_score": top10,
            "median_score": mid,
            "total_members": len(scores),
        }
    return json.dumps(result, ensure_ascii=False)


@tool
def get_worst_group(employee_id: str) -> str:
    """직원의 3개 상품군 점수와 전체 10위 컷을 비교하여, 10위 컷 대비 격차가 가장 큰 상품군 코드와 이름을 반환합니다."""
    conn = _conn()
    c = conn.cursor()
    c.execute("SELECT deposit_score, loan_score, digital_score FROM best_banker_status WHERE employee_id = ?", (employee_id,))
    my = c.fetchone()
    if not my:
        conn.close()
        return json.dumps({"error": f"직원번호 {employee_id}를 찾을 수 없습니다."}, ensure_ascii=False)

    c.execute("SELECT deposit_score, loan_score, digital_score FROM best_banker_status ORDER BY employee_id")
    all_rows = c.fetchall()
    conn.close()

    gaps = {}
    for col, group_code in [("deposit_score", 1), ("loan_score", 2), ("digital_score", 3)]:
        scores = sorted([r[col] for r in all_rows], reverse=True)
        top10 = scores[9] if len(scores) >= 10 else scores[-1]
        gap = my[col] - top10  # 음수일수록 부족
        gaps[group_code] = round(gap, 1)

    worst_group = min(gaps, key=lambda g: gaps[g])

    return json.dumps({
        "worst_group_code": worst_group,
        "worst_group_name": GROUP_NAME[worst_group],
        "gap_to_top10": gaps[worst_group],
        "all_gaps": {GROUP_NAME[g]: v for g, v in gaps.items()},
    }, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════════════════
# Agent 4A — 상품 추천 (고객번호 있을 때)
# ═══════════════════════════════════════════════════════════════════════════════

@tool
def get_top_product_for_customer(customer_id: str, product_group_code: Optional[int] = None) -> str:
    """product_recommendation에서 추천 점수가 가장 높은 상품을 반환합니다.
    product_group_code(1:수신, 2:여신, 3:전자금융) 지정 시 해당 상품군 내 최고 점수 상품을 반환합니다."""
    conn = _conn()
    c = conn.cursor()

    if product_group_code:
        c.execute(
            "SELECT pr.product_code, pr.product_group_code, pr.recommend_score, "
            "bsc.product_name, bsc.add_score "
            "FROM product_recommendation pr "
            "JOIN banker_score_config bsc ON pr.product_code = bsc.product_code "
            "WHERE pr.customer_id = ? AND pr.product_group_code = ? "
            "ORDER BY pr.recommend_score DESC LIMIT 1",
            (customer_id, product_group_code),
        )
    else:
        c.execute(
            "SELECT pr.product_code, pr.product_group_code, pr.recommend_score, "
            "bsc.product_name, bsc.add_score "
            "FROM product_recommendation pr "
            "JOIN banker_score_config bsc ON pr.product_code = bsc.product_code "
            "WHERE pr.customer_id = ? "
            "ORDER BY pr.recommend_score DESC LIMIT 1",
            (customer_id,),
        )

    row = c.fetchone()
    conn.close()

    if not row:
        return json.dumps({"found": False, "message": "해당 조건의 추천 상품이 없습니다."}, ensure_ascii=False)

    return json.dumps({
        "found": True,
        "product_code": row["product_code"],
        "product_name": row["product_name"],
        "product_group_code": row["product_group_code"],
        "product_group_name": GROUP_NAME.get(row["product_group_code"], ""),
        "recommend_score": row["recommend_score"],
        "banker_add_score": row["add_score"],
    }, ensure_ascii=False)


@tool
def generate_marketing_message(customer_summary: str, product_name: str, product_group_name: str) -> str:
    """고객 요약 정보와 추천 상품 정보를 바탕으로 은행원이 고객에게 사용할 마케팅 문구를 생성합니다."""
    from langchain_openai import ChatOpenAI
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser
    from app.core.config import settings
    from pydantic import SecretStr

    llm = ChatOpenAI(
        model=settings.OPENAI_MODEL,
        api_key=SecretStr(settings.OPENAI_API_KEY),
        temperature=0.7,
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "당신은 은행 마케팅 전문가입니다. "
         "고객 특성 요약과 추천 상품 정보를 바탕으로, 은행원이 고객에게 직접 말할 수 있는 "
         "자연스럽고 설득력 있는 마케팅 문구를 2~3문장으로 작성하세요. "
         "고객의 특성과 상품의 장점을 연결하여 개인화된 메시지를 만드세요."),
        ("user",
         "고객 요약: {customer_summary}\n"
         "추천 상품: {product_name} ({product_group_name})\n\n"
         "위 정보를 바탕으로 마케팅 문구를 작성하세요."),
    ])
    chain = prompt | llm | StrOutputParser()
    return chain.invoke({
        "customer_summary": customer_summary,
        "product_name": product_name,
        "product_group_name": product_group_name,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# Agent 4B — 상품 추천 (고객번호 없을 때)
# ═══════════════════════════════════════════════════════════════════════════════

@tool
def get_promoted_customers(employee_id: str) -> str:
    """best_banker_promotion에서 해당 직원이 추진 이력이 있는 고객 ID 목록을 반환합니다."""
    conn = _conn()
    c = conn.cursor()
    c.execute(
        "SELECT DISTINCT customer_id FROM best_banker_promotion WHERE employee_id = ?",
        (employee_id,),
    )
    rows = c.fetchall()
    conn.close()
    customer_ids = [r["customer_id"] for r in rows]
    if not customer_ids:
        return json.dumps({"found": False, "message": f"직원 {employee_id}의 추진 고객이 없습니다.", "customer_ids": []}, ensure_ascii=False)
    return json.dumps({"found": True, "customer_ids": customer_ids, "count": len(customer_ids)}, ensure_ascii=False)


@tool
def get_most_pushed_product_in_group(customer_ids: list[str], product_group_code: int) -> str:
    """get_promoted_customers로 얻은 고객 ID 목록에서 특정 상품군(1:수신, 2:여신, 3:전자금융) 내
    가장 많이 추천된 상품과, 해당 상품이 추천된 고객 목록 및 각 고객의 추천 점수를 반환합니다."""
    if not customer_ids:
        return json.dumps({"found": False, "message": "추진 고객이 없습니다."}, ensure_ascii=False)

    conn = _conn()
    c = conn.cursor()

    placeholders = ",".join("?" * len(customer_ids))

    # 해당 상품군에서 가장 많이 추천된 상품 (추천 건수 기준)
    c.execute(
        f"SELECT product_code, COUNT(*) as cnt "
        f"FROM product_recommendation "
        f"WHERE customer_id IN ({placeholders}) AND product_group_code = ? "
        f"GROUP BY product_code ORDER BY cnt DESC LIMIT 1",
        customer_ids + [product_group_code],
    )
    top_product = c.fetchone()

    if not top_product:
        conn.close()
        return json.dumps({
            "found": False,
            "message": f"추진 고객 중 상품군 {GROUP_NAME.get(product_group_code)} 추천 데이터가 없습니다.",
        }, ensure_ascii=False)

    product_code = top_product["product_code"]

    # 해당 상품이 추천된 고객 목록 + 추천 점수
    c.execute(
        f"SELECT pr.customer_id, pr.recommend_score, cb.customer_name "
        f"FROM product_recommendation pr "
        f"JOIN customer_basic cb ON pr.customer_id = cb.customer_id "
        f"WHERE pr.customer_id IN ({placeholders}) AND pr.product_code = ? "
        f"ORDER BY pr.recommend_score DESC",
        customer_ids + [product_code],
    )
    matched = c.fetchall()

    # 상품명
    c.execute("SELECT product_name FROM banker_score_config WHERE product_code = ?", (product_code,))
    pname_row = c.fetchone()
    conn.close()

    return json.dumps({
        "found": True,
        "product_code": product_code,
        "product_name": pname_row["product_name"] if pname_row else product_code,
        "product_group_code": product_group_code,
        "product_group_name": GROUP_NAME.get(product_group_code, ""),
        "matched_customers": [
            {"customer_id": r["customer_id"], "customer_name": r["customer_name"], "recommend_score": r["recommend_score"]}
            for r in matched
        ],
    }, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════════════════
# Agent 5 — 시뮬레이션
# ═══════════════════════════════════════════════════════════════════════════════

@tool
def get_score_config(product_code: str) -> str:
    """banker_score_config에서 상품코드의 상품군 코드, 상품명, 가점을 반환합니다."""
    conn = _conn()
    c = conn.cursor()
    c.execute("SELECT * FROM banker_score_config WHERE product_code = ?", (product_code,))
    row = c.fetchone()
    conn.close()
    if not row:
        return json.dumps({"error": f"상품코드 {product_code}를 찾을 수 없습니다."}, ensure_ascii=False)
    return json.dumps(dict(row), ensure_ascii=False)


@tool
def simulate_score_change(employee_id: str, product_code: str) -> str:
    """직원이 특정 상품을 추진했을 때의 예상 점수 변화와 전체 순위 변화를 계산합니다.
    현재 점수에 banker_score_config의 add_score를 더해 상품군별/합계 예상 점수와 순위 변화를 반환합니다."""
    conn = _conn()
    c = conn.cursor()

    c.execute("SELECT * FROM best_banker_status WHERE employee_id = ?", (employee_id,))
    my = c.fetchone()
    if not my:
        conn.close()
        return json.dumps({"error": f"직원번호 {employee_id}를 찾을 수 없습니다."}, ensure_ascii=False)

    c.execute("SELECT * FROM banker_score_config WHERE product_code = ?", (product_code,))
    cfg = c.fetchone()
    if not cfg:
        conn.close()
        return json.dumps({"error": f"상품코드 {product_code}를 찾을 수 없습니다."}, ensure_ascii=False)

    group_code = cfg["product_group_code"]
    add_score = cfg["add_score"]
    group_col = GROUP_COL[group_code]

    # 현재 → 변경 후 점수
    current_group_score = my[group_col]
    new_group_score = round(current_group_score + add_score, 1)
    new_total = round(my["total_score"] + add_score, 1)

    # 전체 순위 재계산
    c.execute("SELECT total_score FROM best_banker_status ORDER BY total_score DESC")
    all_totals = [r["total_score"] for r in c.fetchall()]
    conn.close()

    current_rank = sum(1 for s in all_totals if s > my["total_score"]) + 1
    new_rank = sum(1 for s in all_totals if s > new_total) + 1

    return json.dumps({
        "employee_id": employee_id,
        "product_code": product_code,
        "product_name": cfg["product_name"],
        "product_group_code": group_code,
        "product_group_name": GROUP_NAME[group_code],
        "add_score": add_score,
        "before": {
            "group_score": current_group_score,
            "total_score": my["total_score"],
            "rank": current_rank,
        },
        "after": {
            "group_score": new_group_score,
            "total_score": new_total,
            "rank": new_rank,
        },
        "rank_change": current_rank - new_rank,
    }, ensure_ascii=False)
