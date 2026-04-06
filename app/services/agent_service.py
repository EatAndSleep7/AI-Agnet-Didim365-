import asyncio
from datetime import datetime
import json
import os
import uuid

from app.utils.logger import log_execution, custom_logger

from langchain_core.messages import HumanMessage
from langgraph.errors import GraphRecursionError

def _configure_opik():
    """settings.OPIK 값을 기반으로 Opik 환경변수를 설정합니다."""
    from app.core.config import settings

    if settings.OPIK is None:
        return

    opik_settings = settings.OPIK
    if opik_settings.URL_OVERRIDE:
        os.environ["OPIK_URL_OVERRIDE"] = opik_settings.URL_OVERRIDE
    if opik_settings.API_KEY:
        os.environ["OPIK_API_KEY"] = opik_settings.API_KEY
    if opik_settings.WORKSPACE:
        os.environ["OPIK_WORKSPACE"] = opik_settings.WORKSPACE
    if opik_settings.PROJECT:
        os.environ["OPIK_PROJECT_NAME"] = opik_settings.PROJECT

_configure_opik()


class AgentService:
    def __init__(self):
        from langchain_openai import ChatOpenAI
        from app.core.config import settings
        from pydantic import SecretStr

        # LLM 초기화
        self.model = ChatOpenAI(
            model=settings.OPENAI_MODEL,
            api_key=SecretStr(settings.OPENAI_API_KEY),
        )

        # Opik 트레이서 초기화
        self.opik_tracer = None
        if settings.OPIK is not None:
            from opik.integrations.langchain import OpikTracer

            self.opik_tracer = OpikTracer(
                tags=["agent"],
                metadata={"model": settings.OPENAI_MODEL}
            )

        # 대화 이력 저장소: process_query 첫 호출 시 async 초기화
        self.checkpointer = None
        self.agent = None

    async def _init_checkpointer(self):
        """SQLite checkpointer 비동기 초기화 (첫 호출 시 한 번만 실행)"""
        if self.checkpointer is not None:
            return
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        from app.core.config import settings
        conn = await aiosqlite.connect(settings.CHECKPOINTS_DB_PATH)
        self.checkpointer = AsyncSqliteSaver(conn)

    def _create_agent(self):
        """뱅킹 멀티 에이전트 (슈퍼바이저 + 5개 서브 에이전트) 생성"""
        from app.agents.banking_agent import create_banking_agent
        if self.checkpointer is None:
            raise RuntimeError("checkpointer가 초기화되지 않았습니다. _init_checkpointer를 먼저 호출하세요.")
        self.agent = create_banking_agent(
            model=self.model,
            checkpointer=self.checkpointer,
        )

        # opik langgraph 트래킹 적용
        if self.opik_tracer is not None:
            from opik.integrations.langchain import track_langgraph

            self.agent = track_langgraph(self.agent, self.opik_tracer)

    def _build_error_response(self, e: Exception, content: str) -> str:
        """에러 응답 JSON 문자열 생성 (공통 패턴)"""
        payload = {
            "step": "done",
            "message_id": str(uuid.uuid4()),
            "role": "assistant",
            "content": content,
            "metadata": {},
            "created_at": datetime.utcnow().isoformat(),
            "error": str(e) if not isinstance(e, GraphRecursionError) else None,
        }
        return json.dumps(payload, ensure_ascii=False)

    # 실제 대화 로직
    @log_execution
    async def process_query(self, user_messages: str, thread_id: uuid.UUID):
        """LangChain Messages 형식의 쿼리를 처리하고 AIMessage 형식으로 반환합니다."""
        try:
            # checkpointer 초기화 (SQLite 연결, 첫 호출 시만 실행)
            await self._init_checkpointer()
            # 에이전트 초기화 (한 번만)
            self._create_agent()

            custom_logger.info(f"사용자 메시지: {user_messages}")

            # IMP: subgraphs=True 로 서브 에이전트 내부 tool 호출 스텝까지 스트리밍.
            # 각 청크는 (namespace, update) 튜플:
            #   namespace == ()           → 외부 그래프 이벤트 (supervisor, 서브에이전트 완료)
            #   namespace != ()           → 서브에이전트 내부 이벤트 (model, tools 스텝)
            from app.core.config import settings
            agent_stream = self.agent.astream(
                {"messages": [HumanMessage(content=user_messages)]},
                config={
                    "configurable": {"thread_id": str(thread_id)},
                    "recursion_limit": settings.GRAPH_RECURSION_LIMIT,
                },
                stream_mode="updates",
                subgraphs=True,
            )

            _BANKING_SUB_AGENTS = {
                "customer_agent", "regulation_agent",
                "dashboard_agent", "recommendation_agent",
                "strategy_agent", "simulation_agent",
            }

            agent_iterator = agent_stream.__aiter__()
            agent_task = asyncio.create_task(agent_iterator.__anext__())

            while True:
                if agent_task in (done := (await asyncio.wait([agent_task], return_when=asyncio.FIRST_COMPLETED))[0]):
                    try:
                        chunk = agent_task.result()
                    except StopAsyncIteration:
                        agent_task = None
                        break
                    except Exception as e:
                        custom_logger.error(f"Error in agent_task: {e}")
                        import traceback
                        custom_logger.error(traceback.format_exc())
                        agent_task = None
                        yield self._build_error_response(e, "처리 중 오류가 발생했습니다. 다시 시도해주세요.")
                        break

                    # subgraphs=True → chunk = (namespace_tuple, update_dict)
                    namespace, update = chunk
                    custom_logger.info(f"namespace={namespace} update={update}")

                    try:
                        from langchain_core.messages import AIMessage as _AIMessage, ToolMessage as _ToolMessage

                        if namespace == ():
                            # ── 외부 그래프 이벤트 ─────────────────────────────
                            for step, event in update.items():
                                if step == "supervisor":
                                    # 슈퍼바이저 라우팅 알림
                                    yield json.dumps({"step": "model", "tool_calls": ["라우팅 중"]}, ensure_ascii=False)

                                elif step in _BANKING_SUB_AGENTS:
                                    # 서브 에이전트 완료 → 최종 AIMessage 추출 후 done 전송
                                    if not event:
                                        continue
                                    messages = event.get("messages", [])
                                    last_ai = next(
                                        (m for m in reversed(messages) if isinstance(m, _AIMessage)),
                                        None,
                                    )
                                    if last_ai is None:
                                        continue

                                    final_content = last_ai.content
                                    final_metadata = {}
                                    final_message_id = str(uuid.uuid4())

                                    custom_logger.info(f"서브 에이전트 최종 응답: {final_content[:80]}")
                                    yield json.dumps({
                                        "step": "done",
                                        "message_id": final_message_id,
                                        "role": "assistant",
                                        "content": final_content,
                                        "metadata": self._handle_metadata(final_metadata),
                                        "created_at": datetime.utcnow().isoformat(),
                                    }, ensure_ascii=False)

                                elif step == "tools":
                                    if not event:
                                        continue
                                    messages = event.get("messages", [])
                                    if not messages:
                                        continue
                                    message = messages[0]
                                    yield json.dumps({"step": "tools", "name": message.name, "content": ""}, ensure_ascii=False)

                        else:
                            # ── 서브 에이전트 내부 이벤트 (tool 호출 과정 표시) ──
                            # namespace를 순서대로 탐색하여 _BANKING_SUB_AGENTS 에 속하는 첫 이름을 사용.
                            # recommendation_agent처럼 내부에 sub-subgraph가 있을 때도
                            # "path_b" 대신 "recommendation_agent"로 표시된다.
                            agent_name = ""
                            for ns_part in namespace:
                                ns_base = ns_part.split(":")[0]
                                if ns_base in _BANKING_SUB_AGENTS:
                                    agent_name = ns_base
                                    break
                            for step, event in update.items():
                                if not event:
                                    continue
                                messages = event.get("messages", [])
                                if not messages:
                                    continue
                                message = messages[0]

                                if step == "model":
                                    tool_calls = getattr(message, "tool_calls", [])
                                    if not tool_calls:
                                        # 최종 텍스트 응답 — 외부 이벤트에서 done 처리하므로 스킵
                                        continue
                                    # tool 호출 중 알림
                                    yield json.dumps({
                                        "step": "model",
                                        "agent": agent_name,
                                        "tool_calls": [t["name"] for t in tool_calls],
                                    }, ensure_ascii=False)

                                elif step == "tools":
                                    # tool 실행 결과 알림
                                    tool_name = getattr(message, "name", "")
                                    yield json.dumps({
                                        "step": "tools",
                                        "agent": agent_name,
                                        "name": tool_name,
                                        "content": "",
                                    }, ensure_ascii=False)

                    except Exception as e:
                        custom_logger.error(f"Error processing chunk: {e}")
                        import traceback
                        custom_logger.error(traceback.format_exc())
                        yield self._build_error_response(e, "데이터 처리 중 오류가 발생했습니다.")
                        break

                    agent_task = asyncio.create_task(agent_iterator.__anext__())

        except Exception as e:
            import traceback
            custom_logger.error(f"Error in process_query: {e}")
            custom_logger.error(traceback.format_exc())
            yield self._build_error_response(e, "처리 중 오류가 발생했습니다. 다시 시도해주세요.")

    @log_execution
    def _handle_metadata(self, metadata) -> dict:
        custom_logger.info("========================================")
        custom_logger.info(metadata)
        result = {}
        if metadata:
            for k, v in metadata.items():
                result[k] = v
        return result
