# 뱅킹 멀티 에이전트 시스템 (Best Banker Agent)

LangGraph Supervisor 패턴 기반 뱅킹 업무 자동화 멀티 에이전트 시스템입니다.
고객 정보 조회, 규정 검색, 성과 분석, 상품 추천, 추진 전략 수립, 득점 시뮬레이션을 하나의 대화 인터페이스로 처리합니다.

---

## 기술 스택

### 백엔드 프레임워크

| 기술 | 버전 | 용도 |
|---|---|---|
| **FastAPI** | ≥0.104 | REST API 서버, SSE 스트리밍 |
| **Uvicorn** | ≥0.24 | ASGI 서버 |
| **Python** | 3.11 ~ 3.13 | 런타임 |
| **uv** | 최신 | 패키지 매니저 / 가상환경 |

### AI / LLM 오케스트레이션

| 기술 | 버전 | 용도 |
|---|---|---|
| **LangGraph** | ≥0.4 | 멀티 에이전트 그래프 (StateGraph, Supervisor 패턴) |
| **LangChain** | ≥1.0 | LLM 추상화, 도구 정의(`@tool`), ReAct 에이전트 |
| **langchain-openai** | ≥1.0 | OpenAI GPT 모델 연동 |
| **OpenAI API** | GPT-4o | LLM 추론 (structured output, 자유 생성) |
| **langgraph-checkpoint-sqlite** | ≥3.0 | 대화 이력 체크포인터 (AsyncSqliteSaver) |

### 데이터 저장소

| 기술 | 용도 |
|---|---|
| **SQLite** (`banking.db`) | 고객·직원·상품·추천 데이터 (7개 테이블) |
| **SQLite** (`checkpoints.db`) | LangGraph 대화 체크포인트 (멀티턴 이력) |
| **Elasticsearch** | 베스트뱅커 규정집 BM25 검색 (27개 문서, `bestbanker-2025` 인덱스) |

### 설정 / 검증

| 기술 | 용도 |
|---|---|
| **Pydantic v2** | 데이터 모델 정의, `with_structured_output` 스키마 |
| **pydantic-settings** | 환경변수 관리 (`env_nested_delimiter="__"`) |
| **python-dotenv** | `.env` 파일 로드 |

### 관측성 (선택)

| 기술 | 용도 |
|---|---|
| **Opik** | LangGraph 실행 트레이싱 (`OpikTracer`, `track_langgraph`) |

### 테스트 / 코드 품질

| 기술 | 용도 |
|---|---|
| **pytest** + **pytest-asyncio** | 비동기 테스트 (40개) |
| **pytest-cov** | 커버리지 리포트 |
| **ruff** | 린트 |
| **black** | 포맷터 |

---

## 아키텍처

### 요청 흐름

```
POST /api/v1/chat
  │
  ▼
AgentService.process_query()
  │
  ▼
banking_agent.astream(subgraphs=True)
  │  chunk = (namespace, update) 튜플
  │    namespace == ()   → 외부 그래프 이벤트 (supervisor 라우팅, 서브 에이전트 완료)
  │    namespace != ()   → 서브 에이전트 내부 이벤트 (model 추론, tools 실행)
  │
  ▼
StreamingResponse (SSE, text/event-stream)
```

### 멀티 에이전트 구조

```
사용자 메시지
    │
    ▼
[Supervisor] — LLM structured output으로 6개 에이전트 중 하나 선택
    │            최근 6개 메시지 기준 라우팅 (오래된 이력 오염 방지)
    │
    ├─ customer_agent       고객번호 조회 + LLM 한 문장 요약
    ├─ regulation_agent     Elasticsearch BM25/term 규정집 검색 Q&A
    ├─ dashboard_agent      직원 베스트뱅커 점수 비교 리포트
    ├─ recommendation_agent 고객 상품 추천 + 마케팅 문구 (서브그래프)
    ├─ strategy_agent       부족 상품군 추진 전략 (결정론적 Python 노드)
    └─ simulation_agent     상품 추진 시 예상 득점 시뮬레이션
```

### 에이전트 타입

| 에이전트 | 구현 방식 | 이유 |
|---|---|---|
| customer, regulation, dashboard, simulation | `create_react_agent` (ReAct) | 도구 선택·순서가 유연해야 함 |
| recommendation | 커스텀 `StateGraph` + 내부 ReAct | 방향 질문 → A1/A2 분기 흐름이 필요 |
| strategy | 결정론적 `StateGraph` (단일 Python 노드) | LLM 자유 생성 시 불필요한 전략 해설이 추가되는 문제 구조적 방지 |

---

## 서브 에이전트 상세

### 1. customer_agent

| 항목 | 내용 |
|---|---|
| 라우팅 조건 | 고객번호(CUST\d+) 언급 + 고객 정보 조회·요약 요청 |
| 사용 도구 | `get_customer_raw_data`, `summarize_customer` |
| 출력 | 마케팅 관점 한 문장 요약 (잔액, 서비스, 상담 이력, 마케팅 동의 반영) |

---

### 2. regulation_agent

| 항목 | 내용 |
|---|---|
| 라우팅 조건 | 베스트뱅커 규정, 득점기준, 평가배점, 실적산출 대상 등 제도 질의 |
| 사용 도구 | `get_regulation_section` (정확 조회), `search_best_banker_regulations` (BM25) |
| 도구 선택 기준 | 상품군+섹션 명확 → term filter 우선 / 키워드만 있으면 BM25 |
| 출력 | 규정 근거 인용 한국어 답변, 한글 숫자 → 아라비아 숫자 변환 |

---

### 3. dashboard_agent

| 항목 | 내용 |
|---|---|
| 라우팅 조건 | "내 점수", "내 순위", 직원 본인의 성과·실적 조회 |
| 사용 도구 | `get_banker_dashboard` → `get_group_statistics` → `get_worst_group` (순서 고정) |
| 출력 | 상품군별 비교표 (내 점수 / TOP10 / 중앙값 / 격차) + 부족 상품군 + 개선 조언 |

---

### 4. recommendation_agent

커스텀 `StateGraph` 서브그래프로 구성됩니다.

```
START → classify → ask_direction → END   (의도 불명확)
                 → path_a1       → END   (고객 성향 기반)
                 → path_a2       → END   (부족 상품군 기반)
```

**classify 노드 로직:**

1. 최근 4개 메시지를 `_safe_trim`으로 안전하게 추출
2. LLM `with_structured_output(IntentOutput)`으로 A1/A2/null 분류
   - 의도 명확 → A1/A2 직행 (사용자가 "고객 중심으로" 또는 "부족 상품군으로" 명시한 경우)
   - 의도 불명확 → `ask_direction` (단순 "추천해줘" 등)
3. `ask_direction`에서 "1번? 2번?" 질문 후 → 다음 턴 classify에서 재분류

**path_a1 (고객 성향 기반):**
`get_top_product_for_customer(top_n=3)` → `summarize_customer` → TOP3 출력·선택 대기 → `generate_marketing_message`

**path_a2 (부족 상품군 기반):**
`get_worst_group` → `get_top_product_for_customer(category=worst, top_n=3)` → 없으면 category 없이 재호출 → `summarize_customer` → TOP3 출력·선택 대기 → `generate_marketing_message`

---

### 5. strategy_agent

결정론적 `StateGraph` (단일 `run_strategy` Python 노드). LLM은 입력 파싱에만 사용하며 최종 출력은 Python 문자열 템플릿이 생성합니다.

```
START → run_strategy → END
```

**run_strategy 실행 순서:**

1. LLM `with_structured_output(StrategyInput)` → `employee_id`, `target_category` 추출
2. `target_category` 없으면 `get_worst_group`으로 자동 결정
3. `get_promoted_customers(employee_id)` → 추진 이력 고객 목록
4. `get_most_pushed_product_in_group(customer_ids, category)` → 최다 추천 상품
5. matched_customers 각각 `summarize_customer` 호출
6. Python 템플릿으로 AIMessage 조립 (LLM 자유 생성 없음)

**출력 형식:**

```
{상품군}에서 가장 많이 추천된 상품은 **{상품명}**입니다.
해당 상품이 추천된 고객 N명을 안내해드립니다.

---
### {고객명}
**고객 정보 요약** / **추천 상품 및 점수**
---
```

---

### 6. simulation_agent

| 항목 | 내용 |
|---|---|
| 라우팅 조건 | 특정 상품명 언급 + 득점기준·가점·점수 변화 확인 요청 |
| 사용 도구 | `get_banker_dashboard` → `get_product_info` → `get_regulation_section` × 2 |
| 출력 | 현재 점수 + 득점기준 (평점산출방식) + 시뮬레이션 계산 + 실적인정기준 |

금액을 언급한 경우 공식 적용 계산, 언급하지 않은 경우 득점기준만 안내 후 금액 입력 요청.

---

## 도구 (Tools) — 11개

`app/agents/tools.py`

| 도구 | 사용 에이전트 | 설명 |
|---|---|---|
| `get_customer_raw_data` | customer | 3개 테이블 원시 데이터 조회 → JSON |
| `summarize_customer` | customer, recommendation, strategy | LLM 한 문장 요약 (temperature=0.3) |
| `search_best_banker_regulations` | regulation, simulation | ES BM25 자유 검색 |
| `get_regulation_section` | regulation, simulation | ES term filter 정확 조회 |
| `get_banker_dashboard` | dashboard, simulation | 직원 4개 상품군 점수 조회 |
| `get_group_statistics` | dashboard | 전체 직원 TOP10/중앙값 통계 |
| `get_worst_group` | dashboard, recommendation, strategy | TOP10 대비 격차 최대 상품군 도출 |
| `get_top_product_for_customer` | recommendation | 고객 추천 점수 상위 상품 (top_n, category 옵션) |
| `generate_marketing_message` | recommendation | LLM 마케팅 문구 생성 (temperature=0.7) |
| `get_promoted_customers` | strategy | 직원 추진 이력 고객 목록 |
| `get_most_pushed_product_in_group` | strategy | 추진 고객 중 카테고리별 최다 추천 상품 |
| `get_product_info` | simulation | 상품명 LIKE 검색 → 카테고리·규정코드 반환 |

---

## 데이터베이스 스키마

`app/data/banking.db` (SQLite, 7개 테이블)

| 테이블 | 설명 |
|---|---|
| `customer_basic` | 고객 기본 정보 (50명, CUST001~CUST050) |
| `customer_profile` | 고객 라이프스타일·리스크 성향 |
| `customer_consultation` | 상담 이력 (상품명, 반응: 1/0/-1) |
| `best_banker_status` | 직원 4개 상품군 점수 (20명, EMP001~EMP020) |
| `best_banker_promotion` | 직원-고객 추진 이력 |
| `product_master` | 상품 마스터 (카테고리, sub_category, 규정코드) |
| `product_recommendation` | 고객별 상품 추천 점수 |

상품군 코드: `수신(예적금)`, `개인여신`, `기업여신`, `디지털금융`

---

## SSE 스트리밍 이벤트

`POST /api/v1/chat` 응답은 `text/event-stream`으로 스트리밍됩니다.

```jsonc
// 라우팅 중
{"step": "model", "tool_calls": ["라우팅 중"]}

// 서브 에이전트 내부 도구 호출 예고
{"step": "model", "agent": "dashboard_agent", "tool_calls": ["get_banker_dashboard"]}

// 도구 실행 완료
{"step": "tools", "agent": "dashboard_agent", "name": "get_banker_dashboard", "content": ""}

// 최종 응답
{"step": "done", "message_id": "uuid", "role": "assistant", "content": "...", "metadata": {}, "created_at": "..."}
```

---

## 세션 컨텍스트 — 직원번호 자동 주입

Supervisor가 전체 대화 이력에서 `EMP\d+` 패턴으로 직원번호를 추출하고, 라우팅 대상 서브 에이전트의 state에 SystemMessage로 주입합니다.

```python
# banking_agent.py
context = SystemMessage(content=f"[세션 직원번호] {employee_id} — ...")
Command(goto=route, update={"messages": [context]})
```

ReAct 에이전트는 프롬프트에서 이 SystemMessage를 우선 확인하고, `strategy_agent`는 `with_structured_output`으로 직접 추출합니다.

---

## 시작하기

### 1. 환경 설정

```bash
# 의존성 설치
uv sync

# 환경변수 파일 생성
cp env.sample .env
```

### 2. .env 설정

```env
# 필수
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
API_V1_PREFIX=/api/v1

# Elasticsearch (규정 검색)
ES__URL=https://elasticsearch-edu.didim365.app
ES__USER=elastic
ES__PASSWORD=<token>
ES__INDEX=bestbanker-2025

# Opik 트레이싱 (선택)
# OPIK__URL_OVERRIDE=https://opik.example.com
# OPIK__PROJECT=banking-agent
```

### 3. 가상 데이터 생성 (최초 1회)

```bash
uv run python app/data/create_mock_data.py
```

### 4. 서버 실행

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 5. UI 접속

```
http://localhost:8000/banking_ui
```

좌측 채팅 패널 + 우측 Tool Trace 패널 (LLM 호출·도구 실행 과정 시각화)

---

## API 엔드포인트

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/` | API 상태 |
| GET | `/health` | 헬스체크 |
| GET | `/banking_ui` | 통합 UI HTML |
| **POST** | **`/api/v1/chat`** | **에이전트 채팅 (SSE)** |
| GET | `/api/v1/threads` | 대화 세션 목록 |
| GET | `/api/v1/threads/{thread_id}` | 세션 메시지 이력 |
| GET | `/api/v1/favorites/questions` | 즐겨찾기 질문 |
| GET | `/api/v1/mock-db/tables` | 테이블 목록 |
| GET | `/api/v1/mock-db/tables/{name}` | 테이블 데이터 (페이징 `?page=1&page_size=20`) |
| GET | `/api/v1/mock-db/tables/{name}/{id}` | 특정 레코드 |
| GET | `/api/v1/mock-db/stats` | 테이블별 row 수 통계 |

---

## 테스트

```bash
# 전체 테스트 (40개)
uv run pytest -v

# 커버리지
uv run pytest --cov=app tests/ --cov-report=term-missing

# 특정 파일
uv run pytest tests/test_tools.py -v
```

| 파일 | 테스트 수 | 대상 |
|---|---|---|
| `test_main.py` | 2 | 루트/헬스 엔드포인트 |
| `test_mock_db.py` | 8 | Mock DB API (SQL Injection 검증 포함) |
| `test_tools.py` | 13 | 도구 함수 (LLM 모킹 포함) |
| `test_agent_service.py` | 7 | AgentService 스트리밍/에러 처리 |
| `test_chat.py` | 5 | Chat 라우트 SSE 스트리밍 |
| `test_recommendation_routing.py` | 5 | recommendation_agent 헬퍼 함수 |

---

## 프로젝트 구조

```
app/
├── agents/
│   ├── banking_agent.py        # Supervisor + 그래프 조립
│   ├── customer_agent.py
│   ├── regulation_agent.py
│   ├── dashboard_agent.py
│   ├── recommendation_agent.py # 커스텀 StateGraph 서브그래프
│   ├── strategy_agent.py       # 결정론적 Python 노드
│   ├── simulation_agent.py
│   ├── tools.py                # 11개 도구
│   └── prompts.py              # 시스템 프롬프트
├── api/routes/
│   ├── chat.py                 # POST /api/v1/chat
│   ├── mock_db.py
│   └── threads.py
├── core/
│   └── config.py               # pydantic-settings 설정
├── data/
│   ├── banking.db
│   └── create_mock_data.py
├── services/
│   └── agent_service.py        # SSE 스트리밍 처리
└── main.py
```
