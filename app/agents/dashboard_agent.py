from langgraph.prebuilt import create_react_agent
from app.agents.tools import get_banker_dashboard, get_group_statistics, get_worst_group
from app.agents.prompts import BANKER_DASHBOARD_SYSTEM_PROMPT


def create_dashboard_agent(model, checkpointer):
    """Agent 3: 베스트뱅커 현황 파악 에이전트"""
    tools = [get_banker_dashboard, get_group_statistics, get_worst_group]
    return create_react_agent(
        model=model,
        tools=tools,
        prompt=BANKER_DASHBOARD_SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )
