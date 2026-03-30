from langgraph.prebuilt import create_react_agent
from app.agents.tools import search_best_banker_regulations
from app.agents.prompts import REGULATION_QA_SYSTEM_PROMPT


def create_regulation_agent(model, checkpointer):
    """Agent 2: 베스트뱅커 규정 질의응답 에이전트"""
    tools = [search_best_banker_regulations]
    return create_react_agent(
        model=model,
        tools=tools,
        prompt=REGULATION_QA_SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )
