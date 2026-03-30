from langgraph.prebuilt import create_react_agent
from app.agents.tools import get_customer_raw_data, summarize_customer
from app.agents.prompts import CUSTOMER_SUMMARY_SYSTEM_PROMPT


def create_customer_agent(model, checkpointer):
    """Agent 1: 고객 정보 요약 에이전트"""
    tools = [get_customer_raw_data, summarize_customer]
    return create_react_agent(
        model=model,
        tools=tools,
        prompt=CUSTOMER_SUMMARY_SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )
