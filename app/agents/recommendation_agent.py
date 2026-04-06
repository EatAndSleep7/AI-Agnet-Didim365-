"""
상품 추천 서브그래프.

START → classify → {ask_direction | path_a1 | path_a2} → END

- classify     : Python + LLM structured output으로 라우팅 결정
- ask_direction: 고정 문구로 추천 방향 질문 (LLM 없음)
- path_a1      : 고객 성향 기반 추천 (도구 3개)
- path_a2      : 부족 상품군 기반 추천 (도구 4개)

라우팅 원칙:
- 사용자 의도 A1 → path_a1
- 사용자 의도 A2 → path_a2
- 의도 불명 → ask_direction (방향 질문 후 END, 다음 메시지에서 classify 재실행)
"""
import re
from typing import Literal

from langchain_core.messages import AIMessage, SystemMessage
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import create_react_agent
from langgraph.types import Command
from pydantic import BaseModel


# ── State ─────────────────────────────────────────────────────────────────────

class RecommendationState(MessagesState):
    customer_id: str | None
    intent: Literal["A1", "A2"] | None


# ── IntentOutput (structured LLM output) ─────────────────────────────────────

class IntentOutput(BaseModel):
    intent: Literal["A1", "A2"] | None


# ── Helper functions (pure, testable) ─────────────────────────────────────────

def _extract_customer_id(messages: list) -> str | None:
    """메시지 이력에서 CUST로 시작하는 고객번호를 가장 최근 언급된 것으로 반환."""
    for msg in reversed(messages):
        content = msg.content if isinstance(msg.content, str) else ""
        match = re.search(r"\bCUST\d+", content)
        if match:
            return match.group()
    return None


# ── Graph factory ──────────────────────────────────────────────────────────────

def create_recommendation_agent(model, checkpointer):
    """상품 추천 서브그래프를 생성하여 컴파일된 LangGraph를 반환한다."""
    from app.agents.tools import (
        get_worst_group,
        get_top_product_for_customer,
        summarize_customer,
        generate_marketing_message,
    )
    from app.agents.prompts import (
        RECOMMEND_CLASSIFY_PROMPT,
        RECOMMEND_PATH_A1_PROMPT,
        RECOMMEND_PATH_A2_PROMPT,
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

    # ── classify 노드 ──────────────────────────────────────────────────────────
    def classify(state: RecommendationState) -> Command:
        messages = state["messages"]
        customer_id = _extract_customer_id(messages)

        # LLM structured output으로 intent 분류 (직전 AI 질문 포함 위해 최근 4개)
        recent = messages[-4:]
        structured_model = model.with_structured_output(IntentOutput)
        result = structured_model.invoke(
            [SystemMessage(content=RECOMMEND_CLASSIFY_PROMPT)] + recent
        )
        intent = result.intent

        update = {"customer_id": customer_id, "intent": intent}

        if intent == "A1":
            return Command(goto="path_a1", update=update)
        if intent == "A2":
            return Command(goto="path_a2", update=update)
        # intent 불명 → 방향 질문
        return Command(goto="ask_direction", update=update)

    # ── ask_direction 노드 (고정 문구, LLM 없음) ──────────────────────────────
    def ask_direction(_state: RecommendationState) -> dict:
        return {"messages": [AIMessage(
            content="고객 성향 중심으로 추천할까요(1번), 아니면 직원의 부족 상품군 위주로 추천할까요(2번)?"
        )]}

    # ── 그래프 조립 ────────────────────────────────────────────────────────────
    graph = StateGraph(RecommendationState)

    graph.add_node("classify", classify)
    graph.add_node("ask_direction", ask_direction)
    graph.add_node("path_a1", path_a1)
    graph.add_node("path_a2", path_a2)

    graph.add_edge(START, "classify")
    graph.add_edge("ask_direction", END)
    graph.add_edge("path_a1", END)
    graph.add_edge("path_a2", END)

    return graph.compile(checkpointer=checkpointer)
