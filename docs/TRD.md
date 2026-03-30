# Technical Requirements Document (TRD)
## 뱅킹 멀티 에이전트 시스템

---

## 1. 시스템 아키텍처

### 1.1 요청 흐름

```
클라이언트 요청
    ↓
POST /api/v1/chat
    ↓
ChatRouter.chat() → AgentService.process_query()
    ↓
banking_agent.astream(subgraphs=True)
    ↓
supervisor 노드 (LLM 라우팅)
    ├─ customer_agent
    ├─ regulation_agent
    ├─ dashboard_agent
    ├─ recommendation_agent
    └─ simulation_agent
    ↓
StreamingResponse (SSE: Server-Sent Events)
    ↓
클라이언트 수신 (text/event-stream)
```

### 1.2 멀티 에이전트 구조

**Banking Agent (Supervisor Pattern)**
- 사용자 의도 분석 및 적절한 sub-agent로 라우팅
- LLM 기반 라우팅 (사용자 메시지 분석)
- sub-agent 응답 수집 및 반환

**Sub-Agents (5개)**
1. **Customer Agent** — 고객 정보 조회 및 요약
2. **Regulation Agent** — 베스트뱅커 규정 검색
3. **Dashboard Agent** — 직원 실적 분석
4. **Recommendation Agent** — 상품 추천 (경로 A/B)
5. **Simulation Agent** — 점수 시뮬레이션

**특징**
- `astream(subgraphs=True)` 사용으로 sub-agent 내부 tool 호출 단계 노출
- 세션 직원번호(`[세션 직원번호]`)를 supervisor에서 추출하여 sub-agents에 주입
- AsyncSqliteSaver 체크포인터로 대화 이력 저장

---

## 2. 기술 스택

| 계층 | 기술 |
|------|------|
| **Web Framework** | FastAPI 0.104+ |
| **AI Orchestration** | LangGraph 0.0.39+ |
| **LLM** | OpenAI GPT-4o |
| **Database** | SQLite 3 (banking.db) |
| **Conversation Checkpoint** | AsyncSqliteSaver (checkpoints.db) |
| **Regulation Search** | Elasticsearch 8.x (bestbanker-2025 index) |
| **Configuration** | pydantic-settings 2.0+ |
| **Observability** | Opik (선택사항) |
| **HTTP Client** | aiohttp (비동기) |
| **LLM Integration** | LangChain 0.1+ |

**Python Version**: 3.10+

---

## 3. API 명세

### 3.1 Chat (메인 에이전트 상호작용)

**Endpoint**: `POST /api/v1/chat`

**Request**:
```json
{
  "message": "string",
  "thread_id": "uuid (선택사항, 없으면 신규 생성)"
}
```

**Response**: Server-Sent Events (SSE)

각 이벤트는 다음 형식:
```json
{
  "step": "model" | "tools" | "done",
  "tool_calls": ["tool_name1", "tool_name2"],
  "name": "tool_name",
  "content": "string",
  "message_id": "uuid",
  "role": "assistant",
  "metadata": { ... },
  "created_at": "2026-03-26T10:30:00.000000",
  "error": "error_message (optional)"
}
```

**Step 종류**:
- `step="model"` — 에이전트가 LLM을 호출하여 도구 결정 중
  - `tool_calls`: 호출될 도구 목록
- `step="tools"` — 도구 실행 중
  - `name`: 실행 중인 도구명
- `step="done"` — 최종 응답 완료
  - `content`: 자연스러운 한국어 답변
  - `metadata`: 추가 정보 (규정 근거, 테이블 데이터 등)

**예시 응답**:
```
data: {"step": "model", "tool_calls": ["get_customer_raw_data", "summarize_customer"]}

data: {"step": "tools", "name": "get_customer_raw_data", "content": ""}

data: {"step": "done", "message_id": "...", "role": "assistant", "content": "마케팅 동의를 완료한 고액 수신 고객으로, 최근 여신 상품에 긍정적 반응을 보였습니다.", "metadata": {}}
```

---

### 3.2 Threads (대화 이력 조회)

**Endpoint**: `GET /api/v1/threads/{thread_id}`

**Response**:
```json
{
  "thread_id": "uuid",
  "messages": [
    {
      "type": "human" | "ai",
      "content": "string",
      "timestamp": "2026-03-26T10:30:00"
    }
  ]
}
```

---

### 3.3 Favorites (즐겨찾기 관리)

**Endpoint**: `POST /api/v1/favorites`

**Request**:
```json
{
  "thread_id": "uuid",
  "title": "string"
}
```

**Response**:
```json
{
  "id": "uuid",
  "thread_id": "uuid",
  "title": "string",
  "created_at": "2026-03-26T10:30:00"
}
```

---

### 3.4 Mock DB 조회 API

**기본 경로**: `/api/v1/mock-db`

#### 3.4.1 전체 테이블 목록

**Endpoint**: `GET /api/v1/mock-db/tables`

**Response**:
```json
{
  "tables": [
    "customer_basic",
    "customer_profile",
    "customer_consultation",
    "best_banker_status",
    "banker_score_config",
    "best_banker_promotion",
    "product_recommendation"
  ]
}
```

#### 3.4.2 테이블 데이터 조회 (페이징)

**Endpoint**: `GET /api/v1/mock-db/tables/{table_name}?page=1&page_size=20`

**Parameters**:
- `table_name` (path): 테이블명
- `page` (query): 페이지 번호 (기본값: 1)
- `page_size` (query): 페이지 크기 (기본값: 20, 최대: 100)

**Response**:
```json
{
  "table_name": "customer_basic",
  "total_count": 50,
  "page": 1,
  "page_size": 20,
  "total_pages": 3,
  "data": [
    {
      "customer_id": "CUST001",
      "customer_name": "홍길동",
      "balance": 1500000,
      ...
    }
  ]
}
```

#### 3.4.3 특정 레코드 상세 조회

**Endpoint**: `GET /api/v1/mock-db/tables/{table_name}/{id}`

**Parameters**:
- `table_name` (path): 테이블명
- `id` (path): 레코드 ID (CUST###, EMP###, DEP### 등)

**Response**:
```json
{
  "table_name": "customer_basic",
  "record": {
    "customer_id": "CUST001",
    "customer_name": "홍길동",
    "balance": 1500000,
    ...
  }
}
```

#### 3.4.4 테이블 통계

**Endpoint**: `GET /api/v1/mock-db/stats`

**Response**:
```json
{
  "stats": {
    "customer_basic": {
      "count": 50,
      "updated_at": "2026-03-26T10:30:00"
    },
    "customer_profile": {
      "count": 50,
      "updated_at": "2026-03-26T10:30:00"
    },
    ...
  }
}
```

---

## 4. 데이터 모델

### 4.1 SQLite 스키마 (banking.db)

#### 4.1.1 customer_basic
고객 기본 정보

| 컬럼 | 타입 | 설명 |
|-----|------|------|
| customer_id | TEXT (PK) | CUST001~CUST050 |
| customer_name | TEXT | 고객명 |
| age | INTEGER | 나이 |
| balance | REAL | 계좌 잔액 |
| marketing_consent | BOOLEAN | 마케팅 동의 여부 |
| service_subscriptions | TEXT (JSON) | 서비스 가입 목록 |

#### 4.1.2 customer_profile
고객 프로필 (라이프스타일, 소비 패턴)

| 컬럼 | 타입 | 설명 |
|-----|------|------|
| customer_id | TEXT (PK, FK) | CUST001~CUST050 |
| lifestyle | TEXT | lifestyle_segment |
| spending_pattern | TEXT | spending_pattern |
| home_ownership | BOOLEAN | 주택 보유 여부 |
| loan_score | REAL | 대출 신용점수 |

#### 4.1.3 customer_consultation
최근 고객 상담 이력

| 컬럼 | 타입 | 설명 |
|-----|------|------|
| consultation_id | TEXT (PK) | CONS001~ |
| customer_id | TEXT (FK) | CUST001~ |
| consultation_date | TEXT | 상담 날짜 |
| topic | TEXT | 상담 주제 |
| response | TEXT | 반응도 (긍정/부정/중립) |

#### 4.1.4 best_banker_status
직원별 베스트뱅커 점수

| 컬럼 | 타입 | 설명 |
|-----|------|------|
| employee_id | TEXT (PK) | EMP001~EMP020 |
| deposit_score | REAL | 수신(예적금) 점수 |
| loan_score | REAL | 여신(대출) 점수 |
| digital_score | REAL | 전자금융 점수 |
| total_score | REAL | 합계 점수 |
| rank | INTEGER | 순위 |

#### 4.1.5 banker_score_config
상품별 가점 규정

| 컬럼 | 타입 | 설명 |
|-----|------|------|
| product_code | TEXT (PK) | DEP101, LOA201, etc. |
| product_name | TEXT | 상품명 |
| product_group | INTEGER | 상품군 (1=수신, 2=여신, 3=전자금융) |
| points | REAL | 가점 |
| regulation_text | TEXT | 규정 설명 |

#### 4.1.6 best_banker_promotion
상품 추진 이력

| 컬럼 | 타입 | 설명 |
|-----|------|------|
| promotion_id | TEXT (PK) | PROM001~ |
| employee_id | TEXT (FK) | EMP001~ |
| customer_id | TEXT (FK) | CUST001~ |
| product_code | TEXT (FK) | DEP101~ |
| promotion_date | TEXT | 추진 날짜 |

#### 4.1.7 product_recommendation
고객별 상품 추천 점수

| 컬럼 | 타입 | 설명 |
|-----|------|------|
| recommendation_id | TEXT (PK) | REC001~ |
| customer_id | TEXT (FK) | CUST001~ |
| product_code | TEXT (FK) | DEP101~ |
| recommendation_score | REAL | 추천 점수 (0~100) |

---

### 4.2 Elasticsearch 스키마 (bestbanker-2025 index)

**Index Name**: `bestbanker-2025`

**Document Format**:
```json
{
  "_id": "...",
  "title": "규정 제목",
  "text": "규정 본문",
  "category": "규정 카테고리",
  "updated_at": "2026-03-26"
}
```

**검색 필드**: `text` (BM25 검색 대상)

**특징**:
- 총 27개 베스트뱅커 규정 문서
- Korean analyzer 적용
- BM25 알고리즘으로 검색 관련성 계산

---

### 4.3 Checkpointer 스키마 (checkpoints.db)

LangGraph `AsyncSqliteSaver`가 자동 생성합니다.

**저장 정보**:
- `thread_id`: 대화 세션 ID (UUID)
- `messages`: 메시지 이력 (LangChain Message objects)
- `created_at`: 생성 시각
- `updated_at`: 마지막 업데이트 시각

---

## 5. 에이전트 설계

### 5.1 Supervisor 패턴 (Banking Agent)

**역할**: 사용자 의도 분석 및 sub-agent 라우팅

**라우팅 로직**:
```
사용자 메시지 분석
    ↓
고객정보 관련? → customer_agent
규정 질의? → regulation_agent
실적 조회? → dashboard_agent
상품 추천? → recommendation_agent
점수 시뮬레이션? → simulation_agent
판단 불가? → regulation_agent (폴백)
```

**세션 컨텍스트 처리**:
1. Supervisor가 메시지 이력에서 `\bEMP\d+\b` 정규식으로 직원번호 추출
2. 추출된 직원번호를 `[세션 직원번호] {employee_id}` 형식의 SystemMessage로 포장
3. 라우팅 시 해당 sub-agent의 state에 주입
4. Sub-agent는 이 SystemMessage를 우선적으로 사용하여 직원 컨텍스트 유지

---

### 5.2 Customer Agent (고객 정보 요약)

**사용 도구**:
1. `get_customer_raw_data(customer_id)` — customer_basic/profile/consultation 3테이블 조회
2. `summarize_customer(customer_data)` — LLM 기반 마케팅 관점 요약
3. `generate_marketing_message(customer_summary)` — 마케팅 문구 생성

**응답 형식**:
```
한 문장 마케팅 요약: "마케팅 동의를 완료한 고액 수신 고객으로, 최근 여신 상품에 긍정적 반응을 보였습니다."
```

---

### 5.3 Regulation Agent (규정 Q&A)

**사용 도구**:
1. `search_best_banker_regulations(query)` — Elasticsearch BM25 검색
   - 상위 5개 규정 문서 반환
   - 각 문서에 관련성 스코어 포함

**응답 형식**:
```
규정 근거:
- [규정 1] : 내용...
- [규정 2] : 내용...

답변: 자연스러운 한국어 설명...
```

---

### 5.4 Dashboard Agent (실적 분석)

**사용 도구**:
1. `get_banker_dashboard(employee_id)` — 직원 점수 조회
2. `get_group_statistics()` — 전체 직원 10위/중앙값 계산
3. `get_worst_group(employee_id)` — 부족 상품군 자동 도출

**응답 형식**:
```
📊 베스트뱅커 현황 리포트 (EMP001)
────────────────────────────
상품군      | 내 점수 | 10위컷 | 격차
수신(예적금) | 142.5  | 180.0  | -37.5 ← 부족
여신(대출)   | 195.0  | 210.0  | -15.0
전자금융     | 88.0   | 95.0   | -7.0
────────────────────────────
💡 가장 부족: 수신(예적금) — 37.5점 차이
```

---

### 5.5 Recommendation Agent (상품 추천)

**경로 A (고객번호 있음)**:
1. `get_customer_raw_data(customer_id)` — 고객 정보 조회
2. `get_top_product_for_customer(customer_id)` — 추천 점수 최고 상품
3. `generate_marketing_message(customer_summary)` — 마케팅 문구

**경로 B (고객번호 없음)**:
1. `get_worst_group(employee_id)` — 부족 상품군 파악
2. `get_promoted_customers(employee_id, product_group)` — 추진 이력 고객 조회
3. `get_most_pushed_product_in_group(customer_ids, product_group)` — 가장 많이 추진된 상품
4. 각 고객별로 `summarize_customer(customer_id)` 호출 → 대상 고객 목록 생성

**응답 형식 (경로 A)**:
```
추천 상품: 정기예금 플러스 (수신/예적금)
마케팅 문구: 현재 안정적 자산을 보유하신 고객님께, 높은 수익률의 정기예금 상품을 추천드립니다.
```

**응답 형식 (경로 B)**:
```
추천 상품: 정기예금 플러스 (수신/예적금)
대상 고객: 5명
- CUST001 홍길동: 안정적 자산 보유, 고액 수신 고객
- CUST003 김영희: ...
```

---

### 5.6 Simulation Agent (점수 시뮬레이션)

**사용 도구**:
1. `get_banker_dashboard(employee_id)` — 현재 점수 조회
2. `get_score_config(product_code)` — 상품 가점 조회
3. `get_group_statistics()` — 10위/중앙값 재계산
4. `simulate_score_change(employee_id, product_code)` — 시뮬레이션 계산
5. `search_best_banker_regulations(product_code)` — 규정 근거 검색

**응답 형식**:
```
🎯 베스트뱅커 시뮬레이션 (EMP001 / DEP101)
────────────────────────────
상품: 정기예금 플러스
가점: +12.5점

수신 점수 | 142.5 → 155.0 (+12.5)
합계 점수 | 425.5 → 438.0 (+12.5)
순위      | 12위 → 9위 (▲3위)

📋 규정 근거:
정기예금 가입 건당 12.5점 부여, 동일 고객 월 1회 한정...

⚠️ 유의사항: 규정집의 상한선 확인 필수
```

---

## 6. 도구 명세 (Tools)

### 6.1 도구 목록

| # | 도구명 | 입력 | 출력 | 용도 |
|----|--------|------|------|------|
| 1 | `get_customer_raw_data` | customer_id: str | dict | 고객 3테이블 조회 |
| 2 | `summarize_customer` | customer_data: dict | str | LLM 고객 요약 |
| 3 | `search_best_banker_regulations` | query: str | list[dict] | Elasticsearch 규정 검색 |
| 4 | `get_banker_dashboard` | employee_id: str | dict | 직원 점수 조회 |
| 5 | `get_group_statistics` | - | dict | 상품군별 10위/중앙값 |
| 6 | `get_worst_group` | employee_id: str | int | 부족 상품군 파악 |
| 7 | `get_top_product_for_customer` | customer_id: str, product_group: int (선택) | str | 추천 점수 최고 상품 |
| 8 | `generate_marketing_message` | customer_summary: str, product_name: str (선택) | str | 마케팅 문구 생성 |
| 9 | `get_promoted_customers` | employee_id: str, product_group: int | list[str] | 추진 이력 고객 ID |
| 10 | `get_most_pushed_product_in_group` | customer_ids: list[str], product_group: int | dict | 그룹 내 최다 추진 상품 |
| 11 | `get_score_config` | product_code: str | dict | 상품 가점 및 규정 |
| 12 | `simulate_score_change` | employee_id: str, product_code: str | dict | 점수 변화 시뮬레이션 |

---

### 6.2 주요 도구 상세

#### get_customer_raw_data
```python
def get_customer_raw_data(customer_id: str) -> dict
```
**설명**: 고객ID 기반으로 customer_basic, customer_profile, customer_consultation 3개 테이블 조회

**반환**:
```json
{
  "customer_basic": { ... },
  "customer_profile": { ... },
  "customer_consultation": [ ... ]
}
```

---

#### search_best_banker_regulations
```python
def search_best_banker_regulations(query: str) -> list[dict]
```
**설명**: Elasticsearch `bestbanker-2025` 인덱스에서 BM25 검색 (상위 5개)

**반환**:
```json
[
  {
    "_id": "doc_id",
    "title": "규정 제목",
    "text": "규정 본문",
    "score": 8.5
  },
  ...
]
```

---

#### get_worst_group
```python
def get_worst_group(employee_id: str) -> int
```
**설명**: 직원의 3개 상품군 중 10위 컷과의 격차가 가장 큰 부족 상품군 반환

**반환**: 상품군 코드 (1=수신, 2=여신, 3=전자금융)

---

#### get_promoted_customers
```python
def get_promoted_customers(employee_id: str, product_group: int) -> list[str]
```
**설명**: 직원이 특정 상품군에서 추진한 고객 ID 목록 반환

**반환**: ["CUST001", "CUST005", ...]

---

#### get_most_pushed_product_in_group
```python
def get_most_pushed_product_in_group(customer_ids: list[str], product_group: int) -> dict
```
**설명**: 고객 목록에서 특정 상품군 내 가장 많이 추천된 상품 반환

**반환**:
```json
{
  "product_code": "DEP101",
  "product_name": "정기예금 플러스",
  "recommendation_count": 5
}
```

---

## 7. 비기능 요구사항

### 7.1 Streaming & SSE

- **Protocol**: Server-Sent Events (text/event-stream)
- **Format**: `data: {...}\n\n` (JSON 한 줄)
- **Chunk Types**:
  - `step="model"` — 도구 호출 계획
  - `step="tools"` — 도구 실행 중
  - `step="done"` — 최종 응답
- **Encoding**: UTF-8 (ensure_ascii=False for Korean)
- **Timeout**: 기본 3초 이상 걸리는 경우 진행 상황 표시

### 7.2 대화 이력 (Conversation Memory)

- **저장소**: SQLite `checkpoints.db` (AsyncSqliteSaver)
- **식별**: `thread_id` (UUID)
- **저장 정보**: LangChain Message 객체 (HumanMessage, AIMessage)
- **조회**: GET `/api/v1/threads/{thread_id}`
- **생명주기**: 서버 재시작 후에도 유지

### 7.3 세션 컨텍스트 (직원번호 기억)

**구현 방식**:
1. Supervisor가 전체 메시지 이력 검색 (정규식 `\bEMP\d+\b`)
2. 추출된 직원번호를 SystemMessage로 포장
3. 라우팅 시 해당 sub-agent의 state에 추가
4. Sub-agent의 시스템 프롬프트는 이 SystemMessage를 우선 확인

**효과**:
- 중간에 고객 ID 입력해도 직원 컨텍스트 유지
- 도구는 명시적 parameter로만 의존 (암묵적 global state 없음)

### 7.4 Opik 트레이싱 (선택사항)

- **활성화 조건**: `.env`에 `OPIK__URL_OVERRIDE` 또는 `OPIK__PROJECT` 설정
- **트래킹**: `track_langgraph()` decorator 적용
- **메타데이터**: 모델명, 태그 (`agent`) 자동 첨부
- **비활성화**: 설정 없으면 무시 (에러 발생 안 함)

### 7.5 성능 요구사항

| 항목 | 목표 |
|------|------|
| 응답 시간 | < 3초 (규정 검색 포함) |
| 가용성 | > 99% |
| 동시 사용자 | 10명 이상 |
| 데이터베이스 조회 | < 100ms |
| Elasticsearch 검색 | < 500ms |

### 7.6 보안

- **직원 인증**: 은행 내부 네트워크 접근 제한 (프론트엔드 구현)
- **고객 데이터**: 개인정보보호법 준수
  - 고객ID 기반 접근 제어
  - 고객 상담 이력은 직원만 조회 가능
- **Elasticsearch**: 기본 인증 (username/password)
- **OpenAI API Key**: `.env` 파일에서만 로드 (코드 노출 금지)

### 7.7 언어 & 국제화

- **주 언어**: 한국어
- **응답 형식**: 자연스러운 한국어 (반말, 존댓말 혼용 금지)
- **향후 확장**: 다국어 지원 (영문, 중문 등)

---

## 8. 배포 및 운영

### 8.1 로컬 개발

```bash
# 의존성 설치
uv sync

# 가상 데이터 생성 (최초 1회)
uv run python app/data/create_mock_data.py

# 서버 실행 (--reload: 자동 재시작)
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 8.2 테스트

```bash
# 전체 테스트 실행
uv run pytest

# 특정 테스트
uv run pytest tests/test_main.py::test_root_endpoint -v
```

### 8.3 환경 변수

**.env 파일**:
```
# 필수
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
API_V1_PREFIX=/api/v1

# 선택사항
OPIK__URL_OVERRIDE=https://opik-edu.didim365.app/api
OPIK__PROJECT=nh-project-ms

# Elasticsearch
ES__URL=https://elasticsearch-edu.didim365.app
ES__USER=elastic
ES__PASSWORD=...
ES__INDEX=bestbanker-2025
```

### 8.4 로깅 & 모니터링

- **Logger**: `app/utils/logger.py` (custom_logger)
- **레벨**: DEBUG, INFO, WARNING, ERROR
- **Opik Dashboard**: 트레이싱 시각화 (활성화 시)

---

## 9. 확장성 고려사항

### 9.1 새로운 Sub-Agent 추가

1. `app/agents/<name>_agent.py`에 `create_<name>_agent(model, checkpointer)` 함수 작성
2. `app/agents/prompts.py`에 시스템 프롬프트 추가
3. `app/agents/banking_agent.py`에 노드 등록 및 supervisor 라우팅 규칙 업데이트
4. `app/agents/tools.py`에 필요한 도구 추가
5. `app/services/agent_service.py`의 `_BANKING_SUB_AGENTS` set 업데이트

### 9.2 새로운 도구 추가

1. `app/agents/tools.py`에 `@tool` decorator로 함수 정의
2. Sub-agent의 `tools` 파라미터에 추가
3. 관련 system prompt 업데이트

### 9.3 데이터 스케일링

- **Mock DB**: SQLite → PostgreSQL 전환 가능 (ORM 추상화)
- **Elasticsearch**: 인덱스 샤딩 및 복제 구성
- **Checkpointer**: Redis 기반 체크포인터로 전환 가능

---

## 10. 알려진 제약사항

- **상품군 코드**: 현재 3가지 (수신, 여신, 전자금융) 하드코딩됨
- **직원 인증**: 아직 구현 안 됨 (프론트엔드 책임)
- **API 속도 제한**: 미구현 (향후 추가 권장)
- **다국어**: 현재 한국어만 지원

---
