import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from langgraph.errors import GraphRecursionError


async def _collect(gen):
    """비동기 제너레이터에서 모든 청크를 수집"""
    return [chunk async for chunk in gen]


# ── process_query: 정상 응답 ──────────────────────────────────────────────────

async def test_process_query_yields_done_step():
    """서브 에이전트 완료 이벤트 → step=done JSON yield"""
    from langchain_core.messages import AIMessage
    from app.services.agent_service import AgentService

    fake_ai_msg = AIMessage(content="최종 응답입니다.")
    # namespace=() → 외부 그래프 이벤트 (서브 에이전트 완료 경로)
    namespace = ()
    update = {"customer_agent": {"messages": [fake_ai_msg]}}

    async def fake_astream(*args, **kwargs):
        yield (namespace, update)

    svc = AgentService.__new__(AgentService)
    svc.checkpointer = MagicMock()
    svc.agent = MagicMock()
    svc.agent.astream = fake_astream
    svc.opik_tracer = None
    svc.model = MagicMock()

    with patch.object(svc, "_init_checkpointer", new=AsyncMock()):
        with patch.object(svc, "_create_agent"):
            with patch("app.core.config.settings") as mock_settings:
                mock_settings.GRAPH_RECURSION_LIMIT = 50
                chunks = await _collect(svc.process_query("테스트", uuid.uuid4()))

    assert len(chunks) >= 1
    done_chunks = [c for c in chunks if json.loads(c).get("step") == "done"]
    assert done_chunks, "step=done 청크가 없습니다"
    payload = json.loads(done_chunks[0])
    assert payload["content"] == "최종 응답입니다."
    assert payload["role"] == "assistant"


# ── process_query: 에러 처리 ─────────────────────────────────────────────────

async def test_process_query_error_yields_error_json():
    """astream 예외 발생 → 에러 JSON yield (raise 아님)"""
    from app.services.agent_service import AgentService

    async def raise_astream(*args, **kwargs):
        raise RuntimeError("의도적 테스트 오류")
        yield  # 제너레이터 마킹

    svc = AgentService.__new__(AgentService)
    svc.checkpointer = None
    svc.agent = None
    svc.opik_tracer = None
    svc.model = MagicMock()

    with patch.object(svc, "_init_checkpointer", new=AsyncMock()):
        with patch.object(svc, "_create_agent"):
            with patch("app.core.config.settings") as mock_settings:
                mock_settings.GRAPH_RECURSION_LIMIT = 50
                # _create_agent 후 agent 설정
                def setup_agent():
                    svc.checkpointer = MagicMock()
                    svc.agent = MagicMock()
                    svc.agent.astream = raise_astream
                svc._create_agent = setup_agent

                chunks = await _collect(svc.process_query("테스트", uuid.uuid4()))

    assert len(chunks) >= 1
    payload = json.loads(chunks[-1])
    assert payload["step"] == "done"
    assert payload["error"] is not None


async def test_process_query_graph_recursion_error_yields_null_error():
    """GraphRecursionError → error 필드가 None인 JSON yield"""
    from app.services.agent_service import AgentService

    async def recursion_astream(*args, **kwargs):
        raise GraphRecursionError("재귀 한도 초과")
        yield

    svc = AgentService.__new__(AgentService)
    svc.checkpointer = None
    svc.agent = None
    svc.opik_tracer = None
    svc.model = MagicMock()

    def setup_agent():
        svc.checkpointer = MagicMock()
        svc.agent = MagicMock()
        svc.agent.astream = recursion_astream

    svc._create_agent = setup_agent

    with patch.object(svc, "_init_checkpointer", new=AsyncMock()):
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.GRAPH_RECURSION_LIMIT = 50
            chunks = await _collect(svc.process_query("테스트", uuid.uuid4()))

    assert len(chunks) >= 1
    payload = json.loads(chunks[-1])
    assert payload["step"] == "done"
    assert payload["error"] is None


# ── _build_error_response ─────────────────────────────────────────────────────

def test_build_error_response_structure():
    """_build_error_response가 올바른 JSON 구조 반환"""
    from app.services.agent_service import AgentService

    svc = AgentService.__new__(AgentService)
    result = json.loads(svc._build_error_response(ValueError("테스트 오류"), "오류 메시지"))
    assert result["step"] == "done"
    assert result["role"] == "assistant"
    assert result["content"] == "오류 메시지"
    assert result["error"] == "테스트 오류"
    assert "message_id" in result
    assert "created_at" in result


def test_build_error_response_graph_recursion():
    """GraphRecursionError는 error=None"""
    from app.services.agent_service import AgentService

    svc = AgentService.__new__(AgentService)
    result = json.loads(svc._build_error_response(GraphRecursionError(), "재귀 오류"))
    assert result["error"] is None


# ── _handle_metadata ──────────────────────────────────────────────────────────

def test_handle_metadata_empty():
    """빈 dict → 빈 dict 반환"""
    from app.services.agent_service import AgentService

    svc = AgentService.__new__(AgentService)
    assert svc._handle_metadata({}) == {}


def test_handle_metadata_populated():
    """값이 있는 dict → 동일하게 반환"""
    from app.services.agent_service import AgentService

    svc = AgentService.__new__(AgentService)
    result = svc._handle_metadata({"agent": "customer_agent", "count": 3})
    assert result["agent"] == "customer_agent"
    assert result["count"] == 3
