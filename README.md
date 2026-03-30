# 뱅킹 멀티 에이전트 시스템 (Best Banker Agent)

**LangGraph Supervisor 패턴 기반 고급 멀티 에이전트 시스템**으로, 뱅킹 업무(고객 정보, 규정 검색, 성과 분석, 상품 추천, 시뮬레이션)를 자동화합니다.

---

## 🏗️ 아키텍처

```
사용자 질문
    ↓
┌─────────────────────────────────────┐
│       Supervisor (LLM Routing)      │  의도 분석 → 적절한 에이전트 선택
└─────────────┬───────────────────────┘
              ↓
    ┌─────────┴─────────┬───────────┬───────────┬──────────┐
    ↓                   ↓           ↓           ↓          ↓
┌──────────┐ ┌──────────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐
│ Customer │ │ Regulation   │ │Dashboard │ │Recommend │ │ Simulation   │
│ Agent    │ │ Agent        │ │ Agent    │ │ Agent    │ │ Agent        │
└──────────┘ └──────────────┘ └──────────┘ └──────────┘ └──────────────┘
     ↓            ↓                ↓           ↓            ↓
  DB Query   ES (BM25)        DB Query     DB Query    DB Query + ES
   고객정보   베스트뱅커규정    성과대시보드  상품추천    시뮬레이션
```

---

## 📋 5개 Sub-Agent 설명

| 에이전트 | 역할 | 주요 도구 | 데이터 소스 |
|---------|------|---------|----------|
| **Customer** | 고객 정보 조회 및 요약 | `get_customer_raw_data`, `summarize_customer` | SQLite (3 테이블) |
| **Regulation** | 베스트뱅커 규정 Q&A | `search_best_banker_regulations` | Elasticsearch (BM25) |
| **Dashboard** | 직원 성과 분석 및 통계 | `get_banker_dashboard`, `get_group_statistics`, `get_worst_group` | SQLite |
| **Recommendation** | 경로별 상품 추천 (A: 고객ID 있음 / B: 없음) | 6개 도구 조합 | SQLite |
| **Simulation** | 상품 추진 시 예상 점수/순위 변화 | `simulate_score_change`, 규정 인용 | SQLite + ES |

---

## 🚀 시작하기

### 1. 사전 요구사항

- Python 3.11 이상 3.13 이하
- `uv` 패키지 매니저 설치:
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

### 2. 프로젝트 설정

```bash
# 의존성 설치 + 가상환경 생성
uv sync

# .env 파일 생성 (env.sample 기반)
cp env.sample .env
```

### 3. 환경 변수 설정 (.env)

```env
# 필수값
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4o
API_V1_PREFIX=/api/v1

# Elasticsearch 설정 (선택사항, 기본값 포함)
ES__URL=https://elasticsearch-edu.didim365.app
ES__USER=elastic
ES__PASSWORD=<your-token>
ES__INDEX=bestbanker-2025

# Opik 트레이싱 (선택사항)
# OPIK__URL_OVERRIDE=https://opik.example.com
# OPIK__PROJECT=banking-agent
```

### 4. 가상 데이터 생성 (최초 1회)

```bash
uv run python app/data/create_mock_data.py
```

- 50명 고객 (CUST001~CUST050)
- 20명 직원 (EMP001~EMP020)
- 15개 상품 (3개 그룹)
- 데이터베이스: `app/data/banking.db` (SQLite)

### 5. 서버 실행

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 6. UI 접속

**통합 Chat + DB Viewer:**
```
http://localhost:8000/banking_ui
```

- 좌측: 멀티턴 채팅 (대화 이력은 localStorage에 저장)
- 우측: Tool Trace 패널 (LLM Call, Tool 실행 과정 시각화)

---

## 📡 API 엔드포인트

| 메서드 | 경로 | 설명 |
|-------|------|------|
| GET | `/` | API 정보 |
| GET | `/health` | 헬스 체크 |
| GET | `/banking_ui` | 통합 UI HTML 서빙 |
| **POST** | **`/api/v1/chat`** | **에이전트 채팅 (SSE 스트리밍)** |
| GET | `/api/v1/threads` | 대화 세션 목록 |
| GET | `/api/v1/threads/{thread_id}` | 세션 메시지 이력 |
| GET | `/api/v1/favorites/questions` | 즐겨찾기 질문 목록 |
| GET | `/api/v1/mock-db/tables` | 테이블 목록 |
| GET | `/api/v1/mock-db/tables/{name}` | 테이블 데이터 (페이징) |
| GET | `/api/v1/mock-db/tables/{name}/{id}` | 특정 레코드 상세 |
| GET | `/api/v1/mock-db/stats` | 테이블별 통계 |

### POST /api/v1/chat (SSE 스트리밍)

**요청:**
```json
{
  "message": "EMP001의 성과를 분석해줄래?",
  "thread_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**응답 (Server-Sent Events):**
```json
{"step": "model", "tool_calls": ["라우팅 중"]}
{"step": "model", "tool_calls": ["get_banker_dashboard"]}
{"step": "tools", "name": "get_banker_dashboard", "content": ""}
{"step": "done", "message_id": "...", "content": "EMP001은...", "metadata": {}, "created_at": "..."}
```

---

## 🗄️ 데이터베이스 구조

SQLite 7개 테이블 (`app/data/banking.db`):

### 고객 테이블
- **customer_basic** — 고객 기본정보 (ID, 이름, 등급)
- **customer_profile** — 고객 프로필 (신용도, 자산)
- **customer_consultation** — 상담 이력

### 직원/상품 테이블
- **best_banker_status** — 직원별 상품군 점수 (수신/여신/전자금융)
- **banker_score_config** — 상품별 가점표 (상품코드, 점수)

### 추진/추천 테이블
- **best_banker_promotion** — 상품 추진 이력
- **product_recommendation** — 추천 점수 기록

**상품군 코드:**
- `1` = 수신 (예적금)
- `2` = 여신 (대출)
- `3` = 전자금융

---

## 🔧 기술 스택

| 계층 | 기술 |
|------|------|
| **웹 프레임워크** | FastAPI |
| **LLM 에이전트** | LangGraph (Supervisor 패턴) |
| **LLM** | OpenAI API (GPT-4o) |
| **데이터베이스** | SQLite (로컬), Elasticsearch (규정 검색) |
| **대화 이력** | LangGraph AsyncSqliteSaver (checkpoints.db) |
| **관찰성** | Opik (선택사항) |
| **스트리밍** | Server-Sent Events (SSE) |
| **패키지 관리** | uv |

---

## 🧪 테스트

```bash
# 전체 테스트 실행
uv run pytest

# 특정 테스트 실행
uv run pytest tests/test_main.py::test_root_endpoint -v
```

---

## 📌 주요 특징

1. **Supervisor 기반 라우팅**: LLM이 사용자 의도를 분석하여 적절한 sub-agent 선택
2. **세션 컨텍스트 주입**: 대화 이력에서 직원번호(`EMP\d+`)를 추출하여 자동으로 세션 정보 전달
3. **SSE 스트리밍**: 도구 호출 과정을 실시간으로 클라이언트에 전송
4. **Sub-Agent 내부 추적**: `subgraphs=True` 옵션으로 각 에이전트 내부 단계(model/tools)까지 시각화
5. **하이브리드 검색**: SQLite (구조화 데이터) + Elasticsearch (전문 검색)
6. **규정 인용**: 시뮬레이션 시 관련 규정 자동 조회 및 포함

---

## 📂 프로젝트 구조

```
agent/
├── app/
│   ├── agents/                    # 5개 sub-agent + supervisor
│   │   ├── banking_agent.py       # Supervisor 정의
│   │   ├── customer_agent.py      # Agent 1
│   │   ├── regulation_agent.py    # Agent 2
│   │   ├── dashboard_agent.py     # Agent 3
│   │   ├── recommendation_agent.py # Agent 4
│   │   ├── simulation_agent.py    # Agent 5
│   │   ├── tools.py               # 12개 도구 함수
│   │   └── prompts.py             # 5개 시스템 프롬프트
│   ├── api/
│   │   └── routes/                # FastAPI 라우터
│   │       ├── chat.py            # POST /chat
│   │       ├── threads.py         # GET /threads
│   │       └── mock_db.py         # GET /mock-db
│   ├── core/
│   │   └── config.py              # 설정 관리
│   ├── data/
│   │   ├── banking.db             # SQLite DB
│   │   ├── create_mock_data.py    # 데이터 생성 스크립트
│   │   ├── favorite_questions.json # 즐겨찾기
│   │   └── threads.json           # 세션 목록
│   ├── models/
│   │   └── __init__.py            # Pydantic 스키마
│   ├── services/
│   │   └── agent_service.py       # 핵심 스트리밍 로직
│   ├── utils/
│   │   ├── logger.py              # 로깅 헬퍼
│   │   └── read_json.py           # JSON 읽기 헬퍼
│   └── main.py                    # FastAPI 진입점
├── tests/
│   ├── conftest.py                # pytest 픽스처
│   └── test_main.py               # 엔드포인트 테스트
├── banking_ui.html                # 통합 UI
├── CLAUDE.md                      # Claude Code 가이드
├── docs/
│   ├── PRD.md                     # Product Requirements Doc
│   └── TRD.md                     # Technical Requirements Doc
├── env.sample                     # 환경 변수 템플릿
├── pyproject.toml                 # 프로젝트 설정
└── README.md
```

---

## 🔍 Elasticsearch 연결 테스트

```bash
uv run python test_es.py
```

---

## 🛠️ 개발 팁

### 1. 새 에이전트 추가

1. `app/agents/<name>_agent.py` 생성
2. `app/agents/prompts.py`에 시스템 프롬프트 추가
3. `app/agents/banking_agent.py`의 supervisor에 노드 추가
4. `app/services/agent_service.py`의 `_BANKING_SUB_AGENTS` set에 이름 추가

### 2. 새 도구 추가

1. `app/agents/tools.py`에 `@tool` 데코레이터로 함수 작성
2. 해당 에이전트의 프롬프트 업데이트
3. 도구 docstring은 LLM이 사용법을 이해할 수 있도록 명확하게 작성

### 3. 로깅

```python
from app.utils.logger import custom_logger
custom_logger.info("메시지")
```

---

## 📝 라이선스

내부 교육용

---

## 🤝 문의

프로젝트 관련 문의는 CLAUDE.md 참조.
