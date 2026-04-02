import json
import uuid
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient


def _make_payload(message="테스트 질문입니다", thread_id=None):
    return {
        "thread_id": thread_id or str(uuid.uuid4()),
        "message": message,
    }


async def _fake_process_query(*args, **kwargs):
    """AgentService.process_query 대체 — 고정된 SSE 청크 스트림 반환"""
    yield json.dumps({
        "step": "done",
        "message_id": str(uuid.uuid4()),
        "role": "assistant",
        "content": "테스트 응답입니다.",
        "metadata": {},
        "created_at": "2026-01-01T00:00:00",
        "error": None,
    }, ensure_ascii=False)


def test_chat_returns_event_stream(client: TestClient):
    """POST /api/v1/chat → text/event-stream content-type 반환"""
    with patch("app.api.routes.chat.AgentService") as mock_svc_cls:
        mock_svc = mock_svc_cls.return_value
        mock_svc.process_query = _fake_process_query

        with client.stream("POST", "/api/v1/chat", json=_make_payload()) as r:
            assert r.status_code == 200
            assert "text/event-stream" in r.headers["content-type"]


def test_chat_missing_message_returns_422(client: TestClient):
    """message 필드 누락 → 422 Unprocessable Entity"""
    response = client.post("/api/v1/chat", json={"thread_id": str(uuid.uuid4())})
    assert response.status_code == 422


def test_chat_invalid_thread_id_returns_422(client: TestClient):
    """UUID 형식이 아닌 thread_id → 422"""
    response = client.post("/api/v1/chat", json={"thread_id": "not-a-uuid", "message": "hi"})
    assert response.status_code == 422


def test_chat_stream_contains_data_prefix(client: TestClient):
    """SSE 스트림 라인이 'data: ' 접두사로 시작"""
    with patch("app.api.routes.chat.AgentService") as mock_svc_cls:
        mock_svc = mock_svc_cls.return_value
        mock_svc.process_query = _fake_process_query

        with client.stream("POST", "/api/v1/chat", json=_make_payload()) as r:
            lines = [line for line in r.iter_lines() if line.strip()]
            data_lines = [l for l in lines if l.startswith("data: ")]
            assert len(data_lines) > 0, "SSE data 라인이 없습니다"


def test_chat_stream_first_chunk_is_planning(client: TestClient):
    """첫 번째 SSE 청크가 Planning 이벤트"""
    with patch("app.api.routes.chat.AgentService") as mock_svc_cls:
        mock_svc = mock_svc_cls.return_value
        mock_svc.process_query = _fake_process_query

        with client.stream("POST", "/api/v1/chat", json=_make_payload()) as r:
            lines = [line for line in r.iter_lines() if line.startswith("data: ")]
            assert lines, "SSE 데이터가 없습니다"
            first_chunk = json.loads(lines[0][len("data: "):])
            assert first_chunk.get("step") == "model"
            assert "Planning" in first_chunk.get("tool_calls", [])
