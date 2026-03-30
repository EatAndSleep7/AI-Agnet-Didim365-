from langgraph.prebuilt import create_react_agent
from app.agents.tools import (
    get_worst_group,
    get_top_product_for_customer,
    summarize_customer,
    generate_marketing_message,
    get_promoted_customers,
    get_most_pushed_product_in_group,
)
from app.agents.prompts import RECOMMENDATION_SYSTEM_PROMPT


def create_recommendation_agent(model, checkpointer):
    """Agent 4: 상품 추천 에이전트 (고객번호 유무에 따라 분기)"""
    tools = [
        get_worst_group,
        get_top_product_for_customer,
        summarize_customer,
        generate_marketing_message,
        get_promoted_customers,
        get_most_pushed_product_in_group,
    ]
    return create_react_agent(
        model=model,
        tools=tools,
        prompt=RECOMMENDATION_SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )
