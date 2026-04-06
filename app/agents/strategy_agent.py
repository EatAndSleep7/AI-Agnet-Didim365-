"""
베스트뱅커 추진 전략 서브 에이전트 (Hybrid 방식).

- 입력 파싱(employee_id, target_category): LLM structured output으로 유연하게 처리
- 도구 호출 순서 및 출력 포맷팅: 결정론적 Python으로 처리 (LLM 자유 생성 없음)
"""
import json
from typing import Literal

from langchain_core.messages import AIMessage, SystemMessage
from langgraph.graph import StateGraph, MessagesState, START, END
from pydantic import BaseModel


class StrategyInput(BaseModel):
    employee_id: str | None
    target_category: Literal["수신", "개인여신", "기업여신", "디지털금융"] | None


_PARSE_PROMPT = """메시지에서 두 값을 추출하세요.
- employee_id: EMP로 시작하는 직원번호. 없으면 null.
- target_category: 수신|개인여신|기업여신|디지털금융 중 하나. 언급이 없거나 불분명하면 null.
  (예: "개인여신", "아파트 담보", "주택 대출" → 개인여신 / "수신", "예금", "적금" → 수신)"""


def create_strategy_agent(model, checkpointer):
    """베스트뱅커 추진 전략 에이전트를 생성하여 반환한다."""
    from app.agents.tools import (
        get_worst_group,
        get_promoted_customers,
        get_most_pushed_product_in_group,
        summarize_customer,
    )

    def run_strategy(state: MessagesState) -> dict:
        messages = state["messages"]

        # 1. LLM structured output으로 employee_id, target_category 추출
        structured = model.with_structured_output(StrategyInput)
        parsed: StrategyInput = structured.invoke(
            [SystemMessage(content=_PARSE_PROMPT)] + messages[-6:]
        )

        employee_id = parsed.employee_id
        target_category = parsed.target_category

        if not employee_id:
            return {"messages": [AIMessage(content="직원번호(EMP로 시작)를 알 수 없습니다. 직원번호를 알려주세요.")]}

        # 2. target_category 없으면 worst_group으로 결정
        if not target_category:
            worst = json.loads(get_worst_group.invoke({"employee_id": employee_id}))
            if not worst.get("worst_category"):
                return {"messages": [AIMessage(content="부족 상품군 데이터를 찾을 수 없습니다.")]}
            target_category = worst["worst_category"]

        # 3. 추진 고객 목록
        promo = json.loads(get_promoted_customers.invoke({"employee_id": employee_id}))
        if not promo.get("found") or not promo.get("customer_ids"):
            return {"messages": [AIMessage(content="추진 고객 데이터를 찾을 수 없습니다.")]}

        # 4. 최다 추천 상품 조회
        pushed = json.loads(get_most_pushed_product_in_group.invoke(
            {"customer_ids": promo["customer_ids"], "category": target_category}
        ))
        if not pushed.get("found"):
            return {"messages": [AIMessage(content=f"{target_category} 상품군에서 추천 이력을 찾을 수 없습니다.")]}

        product_name = pushed["product_name"]
        matched = pushed["matched_customers"]

        # 5. 고객별 요약 + Python 템플릿으로 포맷팅
        customer_blocks = []
        for c in matched:
            summary = summarize_customer.invoke({"customer_id": c["customer_id"]})
            customer_blocks.append(
                f"### {c['customer_name']}\n\n"
                f"**고객 정보 요약**\n{summary}\n\n"
                f"**추천 상품 및 점수**\n"
                f"{product_name} — 추천점수: {c['recommend_score']}점"
            )

        header = (
            f"{target_category} 상품군에서 상담 이력 고객들에게 "
            f"가장 많이 추천된 상품은 **{product_name}**입니다.\n"
            f"해당 상품이 추천된 고객 {len(matched)}명을 안내해드립니다."
        )
        output = header + "\n\n---\n" + "\n\n---\n".join(customer_blocks)
        return {"messages": [AIMessage(content=output)]}

    graph = StateGraph(MessagesState)
    graph.add_node("run_strategy", run_strategy)
    graph.add_edge(START, "run_strategy")
    graph.add_edge("run_strategy", END)
    return graph.compile(checkpointer=checkpointer)
