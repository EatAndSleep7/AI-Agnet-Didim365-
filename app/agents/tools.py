from __future__ import annotations

import json
import os
import sqlite3
import statistics
from typing import Optional

from elasticsearch import Elasticsearch
from langchain_elasticsearch import ElasticsearchRetriever
from langchain.tools import tool

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "banking.db")

CATEGORY_COL = {
    "수신":     "deposit_score",
    "개인여신": "personal_loan_score",
    "기업여신": "corporate_loan_score",
    "디지털금융": "digital_score",
}


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
        return json.dumps({"found": False, "message": f"고객번호 {customer_id}를 찾을 수 없습니다."}, ensure_ascii=False)

    c.execute("SELECT * FROM customer_profile WHERE customer_id = ?", (customer_id,))
    profile = c.fetchone()

    c.execute(
        "SELECT product_id, product_name, interaction_result, consulted_at "
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
    if not data.get("found", True):
        return data.get("message", "고객 정보를 찾을 수 없습니다.")

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
_es_client: Elasticsearch | None = None


def _bm25_query(q: str) -> dict:
    from app.core.config import settings
    return {
        "query": {"match": {settings.ES.CONTENT_FIELD: {"query": q, "operator": "or"}}},
        "size": settings.ES.TOP_K,
    }


def _build_retriever() -> ElasticsearchRetriever:
    import urllib3
    import warnings
    from app.core.config import settings
    es_cfg = settings.ES
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
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


def _get_es_client() -> Elasticsearch:
    """ES 클라이언트 싱글턴 반환 (SSL 경고 억제)."""
    global _es_client
    if _es_client is None:
        import urllib3
        import warnings
        from app.core.config import settings
        es_cfg = settings.ES
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
            _es_client = Elasticsearch(
                es_cfg.URL,
                basic_auth=(es_cfg.USER, es_cfg.PASSWORD),
                verify_certs=False,
            )
    return _es_client


@tool
def search_best_banker_regulations(query: str) -> str:
    """베스트뱅커 규정집(edu-collection)에서 질문과 관련된 내용을 BM25로 검색하여 반환합니다."""
    retriever = _get_retriever()
    docs = retriever.invoke(query)
    if not docs:
        return f"'{query}'에 대한 규정집 내용을 찾을 수 없습니다."
    parts = [f"[{i+1}] {doc.page_content[:1500]}" for i, doc in enumerate(docs)]
    return "\n\n".join(parts)


@tool
def get_regulation_section(section: str, subsection: str | None = None) -> str:
    """베스트뱅커 규정집에서 상품군(section)과 섹션 유형(subsection)으로 규정 문서를 정확히 조회합니다.

    section: 수신 | 개인여신 | 기업여신 | 디지털금융
    subsection (선택): 평가배점 | 실적산출대상 | 평점산출방식 | 득점기준 | 실적인정기준 | 실적제외대상 | 담당자
      - 없으면 해당 section의 모든 문서 반환
    """
    from app.core.config import settings
    must = [{"term": {"section": section}}]
    if subsection:
        must.append({"term": {"subsection": subsection}})
    body = {
        "query": {"bool": {"must": must}},
        "size": 10,
        "_source": ["section", "subsection", "content_type", "text"],
    }
    es = _get_es_client()
    res = es.search(index=settings.ES.INDEX, body=body)
    hits = res["hits"]["hits"]
    if not hits:
        label = f"{section} > {subsection}" if subsection else section
        return json.dumps({"found": False, "message": f"'{label}' 규정을 찾을 수 없습니다."}, ensure_ascii=False)
    parts = [hit["_source"].get("text", "")[:2000] for hit in hits]
    return "\n\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════════════
# Agent 3 · Agent 4 · Agent 5 공통 — 직원 현황
# ═══════════════════════════════════════════════════════════════════════════════

@tool
def get_banker_dashboard(employee_id: str) -> str:
    """직원번호로 best_banker_status를 조회하여 수신/개인여신/기업여신/디지털금융 점수와 합계를 JSON으로 반환합니다."""
    conn = _conn()
    c = conn.cursor()
    c.execute(
        "SELECT employee_id, deposit_score, personal_loan_score, corporate_loan_score, "
        "digital_score, total_score, last_updated "
        "FROM best_banker_status WHERE employee_id = ?",
        (employee_id,),
    )
    row = c.fetchone()
    conn.close()
    if not row:
        return json.dumps({"found": False, "message": f"직원번호 {employee_id}를 찾을 수 없습니다."}, ensure_ascii=False)
    return json.dumps({"found": True, **dict(row)}, ensure_ascii=False)


@tool
def get_group_statistics() -> str:
    """best_banker_status 전체에서 수신/개인여신/기업여신/디지털금융 각 카테고리의 10위 점수와 중앙값을 JSON으로 반환합니다."""
    conn = _conn()
    c = conn.cursor()
    c.execute(
        "SELECT deposit_score, personal_loan_score, corporate_loan_score, digital_score "
        "FROM best_banker_status ORDER BY employee_id"
    )
    rows = c.fetchall()
    conn.close()

    result = {}
    for col, category in [
        ("deposit_score",        "수신"),
        ("personal_loan_score",  "개인여신"),
        ("corporate_loan_score", "기업여신"),
        ("digital_score",        "디지털금융"),
    ]:
        scores = sorted([r[col] for r in rows], reverse=True)
        top10 = scores[9] if len(scores) >= 10 else scores[-1]
        mid = round(statistics.median(scores), 1)
        result[category] = {
            "top10_score": top10,
            "median_score": mid,
            "total_members": len(scores),
        }
    return json.dumps(result, ensure_ascii=False)


@tool
def get_worst_group(employee_id: str) -> str:
    """직원의 4개 카테고리 점수와 전체 10위의 점수를 비교하여, 10위 대비 격차가 가장 큰 카테고리를 반환합니다."""
    conn = _conn()
    c = conn.cursor()
    c.execute(
        "SELECT deposit_score, personal_loan_score, corporate_loan_score, digital_score "
        "FROM best_banker_status WHERE employee_id = ?",
        (employee_id,),
    )
    my = c.fetchone()
    if not my:
        conn.close()
        return json.dumps({"found": False, "message": f"직원번호 {employee_id}를 찾을 수 없습니다."}, ensure_ascii=False)

    c.execute(
        "SELECT deposit_score, personal_loan_score, corporate_loan_score, digital_score "
        "FROM best_banker_status ORDER BY employee_id"
    )
    all_rows = c.fetchall()
    conn.close()

    gaps = {}
    for col, category in [
        ("deposit_score",        "수신"),
        ("personal_loan_score",  "개인여신"),
        ("corporate_loan_score", "기업여신"),
        ("digital_score",        "디지털금융"),
    ]:
        scores = sorted([r[col] for r in all_rows], reverse=True)
        top10 = scores[9] if len(scores) >= 10 else scores[-1]
        gaps[category] = round(my[col] - top10, 1)  # 음수일수록 부족

    worst = min(gaps, key=lambda g: gaps[g])

    return json.dumps({
        "worst_category": worst,
        "gap_to_top10": gaps[worst],
        "all_gaps": gaps,
    }, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════════════════
# Agent 4A — 상품 추천 (고객번호 있을 때)
# ═══════════════════════════════════════════════════════════════════════════════

@tool
def get_top_product_for_customer(
    customer_id: str,
    category: Optional[str] = None,
    top_n: int = 1,
) -> str:
    """product_recommendation에서 추천 점수가 높은 상품을 최대 top_n개 반환합니다.
    category(수신|개인여신|기업여신|디지털금융) 지정 시 해당 카테고리 내 상위 상품을 반환합니다.
    top_n=1(기본값)이면 단일 결과 형식, top_n>1이면 results 리스트 형식으로 반환합니다."""
    top_n = max(1, min(top_n, 10))
    conn = _conn()
    c = conn.cursor()

    if category:
        c.execute(
            "SELECT pr.product_id, pr.category, pr.recommend_score, pm.product_name, pm.sub_category "
            "FROM product_recommendation pr "
            "JOIN product_master pm ON pr.product_id = pm.product_id "
            "WHERE pr.customer_id = ? AND pr.category = ? "
            "ORDER BY pr.recommend_score DESC LIMIT ?",
            (customer_id, category, top_n),
        )
    else:
        c.execute(
            "SELECT pr.product_id, pr.category, pr.recommend_score, pm.product_name, pm.sub_category "
            "FROM product_recommendation pr "
            "JOIN product_master pm ON pr.product_id = pm.product_id "
            "WHERE pr.customer_id = ? "
            "ORDER BY pr.recommend_score DESC LIMIT ?",
            (customer_id, top_n),
        )

    rows = c.fetchall()
    conn.close()

    if not rows:
        return json.dumps({"found": False, "message": "해당 조건의 추천 상품이 없습니다."}, ensure_ascii=False)

    if top_n == 1:
        row = rows[0]
        return json.dumps({
            "found": True,
            "product_id": row["product_id"],
            "product_name": row["product_name"],
            "category": row["category"],
            "sub_category": row["sub_category"],
            "recommend_score": row["recommend_score"],
        }, ensure_ascii=False)

    results = [
        {
            "rank": i + 1,
            "product_id": row["product_id"],
            "product_name": row["product_name"],
            "category": row["category"],
            "sub_category": row["sub_category"],
            "recommend_score": row["recommend_score"],
        }
        for i, row in enumerate(rows)
    ]
    return json.dumps({"found": True, "count": len(results), "results": results}, ensure_ascii=False)


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
         "당신은 은행원을 위한 영업 문구 전문가입니다. "
         "고객 특성(실제 데이터 기반)과 상품 특성을 연결하여, 은행원이 고객에게 실제로 말할 수 있는 "
         "담백하고 전문적인 문구를 2문장 이내로 작성하세요. "
         "고객의 실제 특성(잔액, 상담이력, 마케팅동의 여부 등)을 반드시 근거로 사용하세요. "
         "'맞춤형', '최적의', '완벽한' 등 근거 없는 추상적 수식어는 사용하지 마세요."),
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
def get_most_pushed_product_in_group(customer_ids: list[str] | str, category: str) -> str:
    """get_promoted_customers로 얻은 고객 ID 목록에서 특정 카테고리(수신|개인여신|기업여신|디지털금융) 내
    가장 많이 추천된 상품과, 해당 상품이 추천된 고객 목록 및 각 고객의 추천 점수를 반환합니다."""
    if isinstance(customer_ids, str):
        customer_ids = [customer_ids]
    customer_ids = customer_ids[:500]  # 과도한 IN 절 방지
    if not customer_ids:
        return json.dumps({"found": False, "message": "추진 고객이 없습니다."}, ensure_ascii=False)

    conn = _conn()
    c = conn.cursor()

    placeholders = ",".join("?" * len(customer_ids))

    # 해당 카테고리에서 가장 많이 추천된 상품 (추천 건수 기준)
    c.execute(
        f"SELECT product_id, COUNT(*) as cnt "
        f"FROM product_recommendation "
        f"WHERE customer_id IN ({placeholders}) AND category = ? "
        f"GROUP BY product_id ORDER BY cnt DESC LIMIT 1",
        customer_ids + [category],
    )
    top_product = c.fetchone()

    if not top_product:
        conn.close()
        return json.dumps({
            "found": False,
            "message": f"추진 고객 중 카테고리 '{category}' 추천 데이터가 없습니다.",
        }, ensure_ascii=False)

    product_id = top_product["product_id"]

    # 해당 상품이 추천된 고객 목록 + 추천 점수
    c.execute(
        f"SELECT pr.customer_id, pr.recommend_score, cb.customer_name "
        f"FROM product_recommendation pr "
        f"JOIN customer_basic cb ON pr.customer_id = cb.customer_id "
        f"WHERE pr.customer_id IN ({placeholders}) AND pr.product_id = ? "
        f"ORDER BY pr.recommend_score DESC",
        customer_ids + [product_id],
    )
    matched = c.fetchall()

    # 상품명
    c.execute("SELECT product_name, sub_category FROM product_master WHERE product_id = ?", (product_id,))
    pm_row = c.fetchone()
    conn.close()

    return json.dumps({
        "found": True,
        "product_id": product_id,
        "product_name": pm_row["product_name"] if pm_row else product_id,
        "category": category,
        "sub_category": pm_row["sub_category"] if pm_row else "",
        "matched_customers": [
            {"customer_id": r["customer_id"], "customer_name": r["customer_name"], "recommend_score": r["recommend_score"]}
            for r in matched
        ],
    }, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════════════════
# Agent 5 — 시뮬레이션
# ═══════════════════════════════════════════════════════════════════════════════

@tool
def get_product_info(product_name: str) -> str:
    """상품명(또는 일부)으로 product_master를 검색하여 카테고리, 세부분류, 규정코드를 반환합니다."""
    conn = _conn()
    c = conn.cursor()
    c.execute(
        "SELECT product_id, category, sub_category, product_name, regulation_code "
        "FROM product_master WHERE product_name LIKE ? AND is_active = 1 LIMIT 5",
        (f"%{product_name}%",),
    )
    rows = c.fetchall()
    conn.close()

    if not rows:
        return json.dumps({"found": False, "message": f"'{product_name}'에 해당하는 상품을 찾을 수 없습니다."}, ensure_ascii=False)

    return json.dumps({
        "found": True,
        "results": [dict(r) for r in rows],
    }, ensure_ascii=False)
