import sqlite3
import pytest
import uuid
from fastapi.testclient import TestClient
from app.main import app
from app.agents.tools import DB_PATH


@pytest.fixture
def client():
    """FastAPI 테스트 클라이언트 fixture"""
    return TestClient(app)


@pytest.fixture
def thread_id():
    """테스트용 thread_id 생성"""
    return str(uuid.uuid4())


@pytest.fixture(scope="session")
def db_conn():
    """banking.db 공유 읽기 전용 연결 (세션 전체)"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()

