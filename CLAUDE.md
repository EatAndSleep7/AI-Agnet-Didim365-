# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# 최초 환경 설정
cp env.sample .env   # OPENAI_API_KEY, ES__PASSWORD 필수 입력

# 의존성 설치 및 가상환경 생성
uv sync

# 서버 실행
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 가상 데이터 생성 (최초 1회)
uv run python app/data/create_mock_data.py

# 전체 테스트 실행 (현재 40개 테스트)
uv run pytest -v

# 테스트 커버리지 리포트
uv run pytest --cov=app tests/ --cov-report=term-missing

# 특정 테스트 함수 실행
uv run pytest tests/test_mock_db.py::test_list_tables -v

# 린트 / 포맷
uv run ruff check .
uv run black --check .

# Elasticsearch 연결 확인
uv run python test_es.py

# 규정 검색 테스트
uv run python -c "from app.agents.tools import search_best_banker_regulations; print(search_best_banker_regulations.invoke('가계여신 평가배점')[:300])"
```

## UI 접근

```
http://localhost:8000/banking_ui   ← 통합 UI (Chat + DB Viewer)
```

`banking_ui.html`이 프로젝트 루트에 위치하며, FastAPI가 `/banking_ui` 경로로 서빙합니다.
같은 origin이므로 CORS 설정 없이 모든 API를 직접 호출합니다.

대화 이력은 **`localStorage`**(`banking_history` 키)에 브라우저 측에서 저장합니다. `/api/v1/threads`는 JSON 파일 기반으로 실제 checkpoints.db와 연동되지 않으므로 UI에서 사용하지 않습니다. 현재 `thread_id`는 `sessionStorage`에 유지되며 새로고침 후 복원됩니다. AI 응답은 `marked.js`로 마크다운 렌더링합니다.

`banking_history` 항목 구조:
```json
{ "thread_id": "uuid", "title": "...", "timestamp": "...", "messages": [...], "trace": [...] }
```
`trace` 필드는 우측 패널 **Tool Trace**의 `traceGroups` 배열을 직렬화한 값입니다. 대화 전환 및 새로고침 시 복원되며, SSE `step=model` 이벤트마다 LLM Call 그룹이, `step=tools`마다 그 안에 도구 항목이 추가됩니다. 라우팅 이벤트(`"Planning"`, `"라우팅 중"`)는 trace에서 제외됩니다.

## Architecture

### 요청 흐름

```
POST /api/v1/chat
  → chat.py (APIRouter)
  → AgentService.process_query()   ← 매 요청마다 새 인스턴스 생성
  → banking_agent.astream(subgraphs=True)
      chunk = (namespace, update) 튜플로 수신
        namespace == ()   → 외부 그래프 이벤트 (supervisor 라우팅, sub-agent 완료)
        namespace != ()   → sub-agent 내부 이벤트 (model 추론, tools 실행 단계)
  → StreamingResponse (SSE)        ← text/event-stream
```

에이전트 응답은 Server-Sent Events(SSE)로 스트리밍됩니다. 각 청크는 `data: {...}\n\n` 형식이며 `step` 필드로 구분됩니다:
- `{"step": "model", "tool_calls": [...]}` — 에이전트가 도구 호출 중 (tool 이름 목록 포함)
- `{"step": "tools", "name": ..., "content": ...}` — 도구 실행 완료
- `{"step": "done", "message_id": ..., "content": ..., "metadata": ...}` — 최종 응답

### API 엔드포인트 전체 목록

| 메서드 | 경로 | 설명 |
|-------|------|------|
| GET | `/` | API 상태 확인 |
| GET | `/health` | 헬스체크 |
| GET | `/banking_ui` | 통합 UI HTML 서빙 |
| POST | `/api/v1/chat` | 에이전트 채팅 (SSE 스트리밍) |
| GET | `/api/v1/threads` | 대화 세션 목록 |
| GET | `/api/v1/threads/{thread_id}` | 특정 세션 메시지 이력 |
| GET | `/api/v1/favorites/questions` | 즐겨찾기 질문 목록 |
| GET | `/api/v1/mock-db/tables` | 테이블 목록 조회 |
| GET | `/api/v1/mock-db/tables/{table_name}` | 테이블 데이터 (페이징: `?page=1&page_size=20`) |
| GET | `/api/v1/mock-db/tables/{table_name}/{id}` | 특정 레코드 조회 |
| GET | `/api/v1/mock-db/stats` | 테이블별 row 수 통계 |

### 뱅킹 멀티 에이전트 구조

`banking_agent.py`가 supervisor 패턴으로 **6개** sub-agent를 조합합니다. `AgentService`는 `/api/v1/chat` 요청마다 새로 인스턴스화되며, `_create_agent()`도 매 요청에 호출됩니다(상태는 `checkpointer`에 영속).

```
banking_agent (supervisor)
  supervisor 노드 → LLM이 사용자 의도 분석 후 Command(goto=route)로 라우팅
    ├─ customer_agent       : customer_basic/profile/consultation 3테이블 조회 + LLM 한 문장 요약
    ├─ regulation_agent     : Elasticsearch bestbanker-2025 BM25 검색 기반 규정 Q&A
    ├─ dashboard_agent      : best_banker_status 분석 + 상품군별 10위/중앙값 통계 + 부족 상품군 도출
    ├─ recommendation_agent : A1/A2 분기 상품 추천 (LangGraph 서브그래프)
    ├─ strategy_agent       : 베스트뱅커 추진 전략 — 결정론적 Python 노드 (LangGraph 서브그래프)
    └─ simulation_agent     : 상품 추진 시 예상 점수/순위 변화 + 규정집 근거
```

대부분의 sub-agent는 `create_react_agent(model, tools, prompt, checkpointer=None)`으로 생성합니다. **단, `strategy_agent`는 예외** — 출력 포맷을 LLM이 아닌 Python이 생성하는 결정론적 `StateGraph`로 구현되어 있습니다. `checkpointer`는 외부 그래프(banking_agent)에만 적용하고, sub-agent에는 `None`을 전달해야 `subgraphs=True` 스트리밍이 정상 동작합니다.

### Sub-agent 응답 처리

`agent_service.py`는 sub-agent 완료 시 마지막 `AIMessage.content`를 그대로 `step="done"` 이벤트의 `content`로 전달합니다. `_BANKING_SUB_AGENTS` set에 에이전트 이름이 등록되어 있어야 Tool Trace 표시가 정상 동작합니다.

새 에이전트를 추가할 때:
1. `app/agents/<name>_agent.py`에 `create_<name>_agent(model, checkpointer)` 팩토리 함수 작성
2. (ReAct 에이전트인 경우) `app/agents/prompts.py`에 시스템 프롬프트 추가
3. `banking_agent.py`의 `AGENTS` Literal, `create_banking_agent()`에 노드 추가, supervisor 프롬프트 업데이트
4. `agent_service.py`의 `_BANKING_SUB_AGENTS` set에 이름 추가
5. `banking_ui.html`의 `AGENT_META`에 `{ label, icon }` 항목 추가

### 추천 에이전트 (recommendation_agent)

LangGraph 서브그래프로 구성됩니다:

```
START → classify → ask_direction → END   (의도 불명 시)
                 → path_a1 → END         (A1: 고객 성향 기반)
                 → path_a2 → END         (A2: 부족 상품군 기반)
```

- **classify**: LLM `with_structured_output(IntentOutput)`으로 A1/A2/null 분류. 최근 4개 메시지 사용 (직전 AI 질문 포함)
- **ask_direction**: LLM 없음, 고정 문구 AIMessage 반환 ("고객 성향 중심(1번)? 부족 상품군(2번)?")
- **path_a1**: `get_top_product_for_customer` → `summarize_customer` → `generate_marketing_message`
- **path_a2**: `get_worst_group` → `get_top_product_for_customer(category=worst)` → `summarize_customer` → `generate_marketing_message`. `{"found": false}` 시 A1 동작으로 폴백하며 사용자에게 안내

### 전략 에이전트 (strategy_agent)

**ReAct 에이전트가 아닙니다.** LLM이 자유롭게 텍스트를 생성하면 전략 해설·상담 조언 등 불필요한 내용이 추가되므로, 출력을 Python 템플릿이 생성하는 결정론적 구조를 사용합니다.

```
START → run_strategy → END
```

`run_strategy` 단일 Python 노드가 순서대로:
1. LLM `with_structured_output(StrategyInput)`으로 `employee_id`, `target_category` 추출 (유연한 입력 처리)
2. `target_category` 없으면 `get_worst_group`으로 결정
3. `get_promoted_customers` → `get_most_pushed_product_in_group` 순으로 직접 invoke
4. 각 matched_customer에 대해 `summarize_customer` invoke
5. Python 문자열 템플릿으로 AIMessage 조립 후 반환

### 테스트

테스트 커버리지: **40개 테스트**

| 파일 | 테스트 수 | 대상 |
|---|---|---|
| `test_main.py` | 2 | 루트/헬스 엔드포인트 |
| `test_mock_db.py` | 8 | Mock DB API (SQL Injection 검증 포함) |
| `test_tools.py` | 13 | 도구 함수 (LLM 모킹 포함) |
| `test_agent_service.py` | 7 | AgentService 스트리밍/에러 처리 |
| `test_chat.py` | 5 | Chat 라우트 SSE 스트리밍 |
| `test_recommendation_routing.py` | 5 | recommendation_agent 라우팅 헬퍼 함수 |

### Tools & 데이터

**도구 (app/agents/tools.py — 11개)**:

| 도구명 | 사용 에이전트 | 역할 |
|---|---|---|
| `get_customer_raw_data` | customer | 고객 3개 테이블 조회 |
| `summarize_customer` | customer, recommendation, strategy | LLM 고객 특성 요약 (온도 0.3) |
| `search_best_banker_regulations` | regulation, simulation | Elasticsearch BM25 규정 검색 |
| `get_banker_dashboard` | dashboard, simulation | 직원 4개 상품군 점수 조회 |
| `get_group_statistics` | dashboard | 전체 직원 상품군별 TOP10/중앙값 |
| `get_worst_group` | dashboard, recommendation, strategy | 직원 부족 상품군 도출 |
| `get_top_product_for_customer` | recommendation | 고객 추천 점수 최고 상품 (category 파라미터 선택) |
| `generate_marketing_message` | recommendation | LLM 마케팅 문구 생성 (온도 0.7) |
| `get_promoted_customers` | strategy | 직원 추진 고객 목록 |
| `get_most_pushed_product_in_group` | strategy | 추진 고객 중 카테고리별 최다 추천 상품 |
| `get_product_info` | simulation | 상품명 검색 및 규정코드 반환 |

`get_most_pushed_product_in_group`은 `customer_ids: list[str]`를 파라미터로 받습니다. 반드시 `get_promoted_customers` 결과를 먼저 받아 전달해야 합니다.

**데이터**:
- `app/data/banking.db` — SQLite, 7개 테이블 (50명 고객, 20명 직원, 15개 상품)
- `app/data/create_mock_data.py` — 가상 데이터 생성 스크립트

상품군 코드: `1=수신(예적금)`, `2=여신(대출)`, `3=전자금융`

### 세션 컨텍스트 (직원번호 기억)

Supervisor가 메시지 이력 전체에서 `\bEMP\d+\b` 정규식으로 직원번호를 추출하여 `[세션 직원번호] EMP###` 형식의 SystemMessage로 포장한 뒤 라우팅되는 sub-agent의 state에 주입합니다. ReAct 기반 에이전트는 이 SystemMessage를 프롬프트에서 우선 확인하도록 작성되어 있으며, `strategy_agent`는 `with_structured_output`으로 메시지에서 직접 추출합니다.

### Opik 트레이싱

`agent_service.py` 모듈 로드 시 `_configure_opik()`이 자동 실행되어 환경변수를 설정합니다. `.env`에 `OPIK__*` 값이 있으면 `OpikTracer`가 초기화되고 `track_langgraph()`로 에이전트에 적용됩니다. Opik 설정이 없으면 무시됩니다.

### 대화 이력 (Checkpointer)

LangGraph의 `AsyncSqliteSaver`를 사용합니다. 기본 경로는 `app/data/checkpoints.db`이며 `CHECKPOINTS_DB_PATH` 환경변수로 재정의할 수 있습니다. `thread_id`(UUID)로 대화 세션을 구분합니다.

### 설정 (`app/core/config.py`)

`pydantic-settings`로 관리하며 `env_nested_delimiter="__"`를 사용합니다. 중첩 설정은 `OPIK__URL_OVERRIDE` 형태의 환경변수로 주입합니다.

### 환경 설정

`.env` 파일을 `env.sample` 기반으로 생성합니다.

**필수값**:
- `OPENAI_API_KEY`, `OPENAI_MODEL`, `API_V1_PREFIX`

**Elasticsearch 설정** (`.env` 또는 `app/core/config.py` 기본값):
- `ES__URL`: `https://elasticsearch-edu.didim365.app`
- `ES__USER`: `elastic`
- `ES__PASSWORD`: API 토큰 (기본값 없음, `.env`에 반드시 설정)
- `ES__INDEX`: `bestbanker-2025` (베스트뱅커 규정 인덱스, 27개 문서)
- `ES__CONTENT_FIELD`: `text`
- `ES__TOP_K`: `5` (BM25 검색 결과 수)

**Opik 설정** (선택사항):
- `OPIK__URL_OVERRIDE`: Opik 서버 URL
- `OPIK__PROJECT`: 프로젝트 이름
