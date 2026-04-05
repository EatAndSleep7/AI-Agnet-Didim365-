"""
상품 추천 서브그래프.

START → classify → {ask_intent | ask_strategy | path_a1 | path_a2 | path_b} → END

- classify     : Python + LLM structured output으로 라우팅 결정
- ask_intent   : 고객번호 있을 때 추천 방향 질문 (도구 없음)
- ask_strategy : 고객번호 없을 때 전략/고객번호 요청 (도구 없음)
- path_a1      : 고객 성향 기반 추천 (도구 3개)
- path_a2      : 부족 상품군 기반 추천 (도구 4개)
- path_b       : 추진 이력 기반 전략 (도구 4개)
"""
import re
from typing import Literal

from langchain_core.messages import SystemMessage
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import create_react_agent
from langgraph.types import Command
from pydantic import BaseModel


# ── State ─────────────────────────────────────────────────────────────────────

class RecommendationState(MessagesState):
    customer_id: str | None
    explicit_category: str | None
    intent: Literal["A1", "A2", "B"] | None


# ── IntentOutput (structured LLM output) ─────────────────────────────────────

class IntentOutput(BaseModel):
    intent: Literal["A1", "A2", "B"] | None


# ── Helper functions (pure, testable) ─────────────────────────────────────────

# 키워드는 긴 것 먼저 — "기업여신"이 "여신"보다 먼저 매칭돼야 한다
_CATEGORY_KEYWORDS: list[tuple[str, str]] = [
    ("기업여신", "기업여신"),
    ("개인여신", "개인여신"),
    ("디지털금융", "디지털금융"),
    ("전자금융", "디지털금융"),
    ("디지털", "디지털금융"),
    ("여신", "개인여신"),
    ("수신", "수신"),
]


def _extract_customer_id(messages: list) -> str | None:
    """메시지 이력에서 CUST로 시작하는 고객번호를 가장 최근 언급된 것으로 반환."""
    for msg in reversed(messages):
        content = msg.content if isinstance(msg.content, str) else ""
        match = re.search(r"\bCUST\d+", content)
        if match:
            return match.group()
    return None


def _extract_explicit_category(messages: list) -> str | None:
    """메시지 이력에서 상품군 키워드를 처음 발견한 것 반환. 긴 키워드 우선."""
    for msg in messages:
        content = msg.content if isinstance(msg.content, str) else ""
        for keyword, category in _CATEGORY_KEYWORDS:
            if keyword in content:
                return category
    return None


# ── Graph factory ──────────────────────────────────────────────────────────────

def create_recommendation_agent(model, checkpointer):
    """상품 추천 서브그래프를 생성하여 컴파일된 LangGraph를 반환한다."""
    from app.agents.tools import (
        get_worst_group,
        get_top_product_for_customer,
        summarize_customer,
        generate_marketing_message,
        get_promoted_customers,
        get_most_pushed_product_in_group,
    )
    from app.agents.prompts import (
        RECOMMEND_CLASSIFY_PROMPT,
        RECOMMEND_ASK_INTENT_PROMPT,
        RECOMMEND_ASK_STRATEGY_PROMPT,
        RECOMMEND_PATH_A1_PROMPT,
        RECOMMEND_PATH_A2_PROMPT,
        RECOMMEND_PATH_B_PROMPT,
    )

    # ── path 노드 (각 경로 전용 도구만) ──────────────────────────────────────
    path_a1 = create_react_agent(
        model=model,
        tools=[get_top_product_for_customer, summarize_customer, generate_marketing_message],
        prompt=RECOMMEND_PATH_A1_PROMPT,
        checkpointer=None,
    )
    path_a2 = create_react_agent(
        model=model,
        tools=[get_worst_group, get_top_product_for_customer, summarize_customer, generate_marketing_message],
        prompt=RECOMMEND_PATH_A2_PROMPT,
        checkpointer=None,
    )
    path_b = create_react_agent(
        model=model,
        tools=[get_worst_group, get_promoted_customers, get_most_pushed_product_in_group, summarize_customer],
        prompt=RECOMMEND_PATH_B_PROMPT,
        checkpointer=None,
    )

    # ── classify 노드 ──────────────────────────────────────────────────────────
    def classify(state: RecommendationState) -> Command:
        messages = state["messages"]

        customer_id = _extract_customer_id(messages)
        explicit_category = _extract_explicit_category(messages)

        # fast-path: 고객번호 없음 + 상품군 명시 → 즉시 B
        if not customer_id and explicit_category:
            injection = SystemMessage(
                content=f"[target_category] {explicit_category} — 사용자가 이 상품군을 명시했습니다. get_worst_group 호출 없이 이 값을 사용하세요."
            )
            return Command(
                goto="path_b",
                update={
                    "customer_id": None,
                    "explicit_category": explicit_category,
                    "intent": "B",
                    "messages": [injection],
                },
            )

        # LLM structured output으로 intent 분류 (최근 3개 메시지만)
        recent = messages[-3:]
        structured_model = model.with_structured_output(IntentOutput)
        result = structured_model.invoke(
            [SystemMessage(content=RECOMMEND_CLASSIFY_PROMPT)] + recent
        )
        intent = result.intent

        update = {
            "customer_id": customer_id,
            "explicit_category": explicit_category,
            "intent": intent,
        }

        if intent == "A1":
            return Command(goto="path_a1", update=update)
        if intent == "A2":
            return Command(goto="path_a2", update=update)
        if intent == "B":
            return Command(goto="path_b", update=update)
        if customer_id:
            return Command(goto="ask_intent", update=update)
        return Command(goto="ask_strategy", update=update)

    # ── ask 노드 (도구 없음, 단순 LLM 호출) ──────────────────────────────────
    def ask_intent(state: RecommendationState) -> dict:
        response = model.invoke(
            [SystemMessage(content=RECOMMEND_ASK_INTENT_PROMPT)] + state["messages"]
        )
        return {"messages": [response]}

    def ask_strategy(state: RecommendationState) -> dict:
        response = model.invoke(
            [SystemMessage(content=RECOMMEND_ASK_STRATEGY_PROMPT)] + state["messages"]
        )
        return {"messages": [response]}

    # ── 그래프 조립 ────────────────────────────────────────────────────────────
    graph = StateGraph(RecommendationState)

    graph.add_node("classify", classify)
    graph.add_node("ask_intent", ask_intent)
    graph.add_node("ask_strategy", ask_strategy)
    graph.add_node("path_a1", path_a1)
    graph.add_node("path_a2", path_a2)
    graph.add_node("path_b", path_b)

    graph.add_edge(START, "classify")
    graph.add_edge("ask_intent", END)
    graph.add_edge("ask_strategy", END)
    graph.add_edge("path_a1", END)
    graph.add_edge("path_a2", END)
    graph.add_edge("path_b", END)

    return graph.compile(checkpointer=checkpointer)
