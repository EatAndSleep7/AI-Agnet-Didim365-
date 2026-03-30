"""
슈퍼바이저 에이전트: 사용자 의도에 따라 5개 서브 에이전트 중 하나로 라우팅합니다.

라우팅 기준:
- 고객 정보 요약    → customer_agent    (고객번호 조회/요약 요청)
- 규정 질의응답     → regulation_agent  (규정, 정책, 기준 질문)
- 베스트뱅커 현황   → dashboard_agent   (내 점수, 순위, 현황, 부족 상품군)
- 상품 추천         → recommendation_agent (상품 추천, 마케팅 문구)
- 시뮬레이션        → simulation_agent  (추진 시 점수 변화, 시뮬레이션)
"""
import re
from typing import Literal

from pydantic import BaseModel
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.types import Command


SUPERVISOR_SYSTEM_PROMPT = """당신은 뱅킹 멀티 에이전트 시스템의 슈퍼바이저입니다.
사용자의 메시지를 분석하여 아래 5개 에이전트 중 하나를 선택하세요.

에이전트 선택 기준:
- customer_agent    : CUST로 시작하는 고객번호가 언급되며 고객 정보 조회/요약을 요청할 때
- regulation_agent  : 규정, 정책, 기준, 평가 방식 등 규정집 내용을 질문할 때
- dashboard_agent   : 내 점수, 내 순위, 현황, 부족 상품군 등 직원 본인의 베스트뱅커 성과를 물을 때
- recommendation_agent : 상품 추천, 마케팅 문구 생성을 요청할 때
- simulation_agent  : 특정 상품을 추진했을 때 점수/순위 변화를 시뮬레이션할 때

[직원번호: EMP###] 형태의 컨텍스트는 세션 정보이며 라우팅 판단에 사용하지 마세요.
반드시 위 5개 중 정확히 하나의 에이전트 이름만 route 필드에 반환하세요."""

AGENTS = Literal[
    "customer_agent",
    "regulation_agent",
    "dashboard_agent",
    "recommendation_agent",
    "simulation_agent",
]


class RouteOutput(BaseModel):
    route: AGENTS


def create_banking_agent(model, checkpointer):
    """슈퍼바이저 + 5개 서브 에이전트를 조합한 멀티 에이전트 그래프를 생성합니다."""
    from app.agents.customer_agent import create_customer_agent
    from app.agents.regulation_agent import create_regulation_agent
    from app.agents.dashboard_agent import create_dashboard_agent
    from app.agents.recommendation_agent import create_recommendation_agent
    from app.agents.simulation_agent import create_simulation_agent

    # 서브 에이전트 생성 — 컴파일된 그래프를 직접 노드로 추가해야
    # subgraphs=True 스트리밍 시 내부 tool 호출 스텝이 노출됨
    customer_agent = create_customer_agent(model, checkpointer=None)
    regulation_agent = create_regulation_agent(model, checkpointer=None)
    dashboard_agent = create_dashboard_agent(model, checkpointer=None)
    recommendation_agent = create_recommendation_agent(model, checkpointer=None)
    simulation_agent = create_simulation_agent(model, checkpointer=None)

    # ── 슈퍼바이저 노드 ──────────────────────────────────────────────────────

    def supervisor(state: MessagesState) -> Command[AGENTS]:
        """사용자 메시지를 분석하여 적절한 서브 에이전트로 라우팅"""
        from langchain_core.messages import SystemMessage

        # 대화 이력에서 최초 등장한 직원번호를 세션 ID로 추출 (EMP001 형태)
        employee_id = None
        for msg in state["messages"]:
            content = msg.content if isinstance(msg.content, str) else ""
            match = re.search(r"\bEMP\d+\b", content)
            if match:
                employee_id = match.group()
                break

        messages = [SystemMessage(content=SUPERVISOR_SYSTEM_PROMPT)] + state["messages"]
        structured_model = model.with_structured_output(RouteOutput)
        response = structured_model.invoke(messages)
        route = response.route

        if employee_id:
            context = SystemMessage(
                content=f"[세션 직원번호] {employee_id} — 이번 요청에서 직원번호가 명시되지 않은 경우 반드시 이 값을 사용하세요."
            )
            return Command(goto=route, update={"messages": [context]})

        return Command(goto=route)

    # ── 그래프 조립 ──────────────────────────────────────────────────────────
    # 서브 에이전트 컴파일 그래프를 직접 노드로 추가 → subgraphs=True 시 내부 스텝 노출

    graph = StateGraph(MessagesState)

    graph.add_node("supervisor", supervisor)
    graph.add_node("customer_agent", customer_agent)
    graph.add_node("regulation_agent", regulation_agent)
    graph.add_node("dashboard_agent", dashboard_agent)
    graph.add_node("recommendation_agent", recommendation_agent)
    graph.add_node("simulation_agent", simulation_agent)

    graph.add_edge(START, "supervisor")
    graph.add_edge("customer_agent", END)
    graph.add_edge("regulation_agent", END)
    graph.add_edge("dashboard_agent", END)
    graph.add_edge("recommendation_agent", END)
    graph.add_edge("simulation_agent", END)

    return graph.compile(checkpointer=checkpointer)
