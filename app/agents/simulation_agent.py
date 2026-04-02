from langgraph.prebuilt import create_react_agent
from app.agents.tools import (
    get_product_info,
    search_best_banker_regulations,
)
from app.agents.prompts import SIMULATION_SYSTEM_PROMPT


def create_simulation_agent(model, checkpointer):
    """Agent 5: 베스트뱅커 시뮬레이션 에이전트"""
    tools = [
        get_product_info,
        search_best_banker_regulations,
    ]
    return create_react_agent(
        model=model,
        tools=tools,
        prompt=SIMULATION_SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )
