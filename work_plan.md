# 뱅킹 멀티 에이전트 시스템 작업계획서

## 개요

은행원이 고객 응대 및 베스트뱅커 실적 관리를 위해 사용하는 5개의 LangGraph 서브 에이전트를 구현한다.
각 에이전트는 독립적으로 동작하며, 슈퍼바이저 에이전트가 사용자 의도에 따라 라우팅을 담당한다.

---

## 전제 조건

| 항목 | 내용 |
|------|------|
| LLM | GPT-4o (`settings.OPENAI_MODEL`) |
| 프레임워크 | LangGraph + LangChain |
| DB | SQLite (`banking.db`, 7개 테이블) |
| RAG | Elasticsearch `bestbanker-2025` 인덱스 (베스트뱅커 규정집, 27개 문서) |
| 트레이싱 | Opik (`OpikTracer` + `track_langgraph`) |

---

## DB 스키마

### 고객 기본정보 테이블 `customer_basic`

```sql
CREATE TABLE IF NOT EXISTS customer_basic (
    customer_id TEXT PRIMARY KEY,           -- 고객번호 (PK)
    customer_name TEXT NOT NULL,            -- 고객명
    deposit_balance REAL DEFAULT 0,         -- 수신(예적금) 잔액
    loan_balance REAL DEFAULT 0,            -- 여신(대출) 잔액
    is_mobile_banking_active INTEGER DEFAULT 0,    -- 모바일뱅킹 활성화
    is_open_banking_joined INTEGER DEFAULT 0,      -- 오픈뱅킹 가입
    is_mydata_joined INTEGER DEFAULT 0,            -- 마이데이터 가입
    has_salary_transfer INTEGER DEFAULT 0,         -- 급여이체 등록
    has_utility_auto_transfer INTEGER DEFAULT 0,   -- 공과금 자동이체 등록
    is_marketing_agreed INTEGER DEFAULT 0          -- 마케팅 동의 여부
);
```

### 고객 추정 요소 테이블 `customer_profile`

```sql
CREATE TABLE IF NOT EXISTS customer_profile (
    customer_id TEXT PRIMARY KEY,
    is_married_estimated INTEGER DEFAULT 0,    -- 결혼 추정
    has_car_estimated INTEGER DEFAULT 0,       -- 자동차 보유 추정
    has_children_estimated INTEGER DEFAULT 0,  -- 자녀 보유 추정
    is_homeowner_estimated INTEGER DEFAULT 0,  -- 자가 주택 보유 추정
    avg_weekend_spend_count INTEGER DEFAULT 0, -- 주말 평균 결제 건수
    avg_night_spend_count INTEGER DEFAULT 0,   -- 심야 결제 건수
    last_contact_elapsed_days INTEGER DEFAULT 0, -- 마지막 접촉 후 경과일
    FOREIGN KEY (customer_id) REFERENCES customer_basic (customer_id)
);
```

### 고객 상담 이력 테이블 `customer_consultation`

```sql
CREATE TABLE IF NOT EXISTS customer_consultation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT NOT NULL,
    product_code TEXT,
    product_name TEXT,
    interaction_result INTEGER DEFAULT 0,  -- -1: 부정, 0: 중립, 1: 긍정
    consulted_at TEXT,                     -- YYYY-MM-DD HH:MM:SS
    FOREIGN KEY (customer_id) REFERENCES customer_basic (customer_id)
);
```

### 베스트뱅커 현황 테이블 `best_banker_status`

```sql
CREATE TABLE IF NOT EXISTS best_banker_status (
    employee_id TEXT PRIMARY KEY,
    deposit_score REAL DEFAULT 0.0,   -- 수신(예적금) 상품군 점수
    loan_score REAL DEFAULT 0.0,      -- 여신(대출) 상품군 점수
    digital_score REAL DEFAULT 0.0,   -- 전자금융 상품군 점수
    total_score REAL DEFAULT 0.0,     -- 합계 점수
    last_updated TEXT                 -- 최종 집계 일시
);
```

### 베스트뱅커 계산 테이블 `banker_score_config`

```sql
CREATE TABLE IF NOT EXISTS banker_score_config (
    product_code TEXT PRIMARY KEY,
    product_group_code INTEGER,  -- 1:수신, 2:여신, 3:전자금융
    product_name TEXT,
    add_score REAL DEFAULT 0.0   -- 가입 시 부여 가점
);
```

### 베스트뱅커 추진 테이블 `best_banker_promotion`

```sql
CREATE TABLE IF NOT EXISTS best_banker_promotion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    product_group_code INTEGER NOT NULL,  -- 1:수신, 2:여신, 3:전자금융
    product_code TEXT NOT NULL,
    promotion_date TEXT DEFAULT (DATETIME('now', 'localtime')),
    FOREIGN KEY (employee_id) REFERENCES best_banker_status (employee_id),
    FOREIGN KEY (customer_id) REFERENCES customer_basic (customer_id)
);
```

### 상품 추천 테이블 `product_recommendation`

```sql
CREATE TABLE IF NOT EXISTS product_recommendation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT,                    -- 고객번호 (FK)
    product_group_code INTEGER,          -- 상품군코드 (1:수신, 2:여신, 3:전자금융)
    product_code TEXT,                   -- 추천 상품코드
    recommend_score INTEGER,             -- 추천 점수 (1~1000, 높을수록 유망)
    FOREIGN KEY (customer_id) REFERENCES customer_basic (customer_id)
);
```

---

## 상품군 코드 참조

| product_group_code | 상품군 | best_banker_status 컬럼 |
|--------------------|--------|------------------------|
| 1 | 수신(예적금) | `deposit_score` |
| 2 | 여신(대출) | `loan_score` |
| 3 | 전자금융 | `digital_score` |

---

## 가상 데이터 생성 계획

신규 스키마 기반의 `banking.db`를 생성하고, 각 테이블에 가상 데이터를 삽입한다.

| 테이블 | 데이터 규모 | 비고 |
|--------|------------|------|
| `customer_basic` | 50건 | customer_id: CUST001~CUST050 |
| `customer_profile` | 50건 | customer_basic 1:1 대응 |
| `customer_consultation` | 150건 | 고객당 평균 3건 |
| `best_banker_status` | 20건 | employee_id: EMP001~EMP020 |
| `banker_score_config` | 15건 | 상품군별 5개 상품 |
| `best_banker_promotion` | 80건 | 직원-고객 추진 이력 |
| `product_recommendation` | 고객(50) × 상품군(3) × 상품(5) = 최대 750건 | recommend_score: 1~1000 랜덤 |

**생성 파일**: `app/data/create_mock_data.py`

---

## 에이전트별 구현 계획

---

### Agent 1: 고객 정보 요약 에이전트

**목적**: 고객번호 기반으로 3개 테이블을 조회하고 LLM으로 한 문장 요약 생성

**입력**: `customer_id` (TEXT, 예: `"CUST012"`)

**처리 흐름**:
```
customer_id 입력
  → get_customer_raw_data(customer_id)
      ├─ customer_basic     : 기본정보, 잔액, 서비스 가입 현황, 마케팅 동의
      ├─ customer_profile   : 라이프스타일 추정, 소비 패턴
      └─ customer_consultation : 최근 상담 이력 (상품명, 반응, 일시)
  → LLM 요약 프롬프트
      └─ 핵심 특성을 마케팅 관점에서 한 문장으로
  → 요약 문구 반환
```

**신규 Tool**:
```python
@tool
def get_customer_raw_data(customer_id: str) -> str:
    """고객번호로 customer_basic, customer_profile, customer_consultation 3개 테이블을 조회하여 JSON으로 반환합니다."""

@tool
def summarize_customer(customer_id: str) -> str:
    """고객 3개 테이블 데이터를 조회 후 LLM으로 한 문장 마케팅 요약을 생성합니다."""
```

**요약 프롬프트 핵심 지침**:
- 단순 나열 금지, 핵심 특성 중심
- 마케팅 동의 여부, 상담 반응(interaction_result), 잔액 규모를 가중 반영
- 예: "마케팅 동의를 완료한 고액 수신 고객으로, 최근 여신 상품에 긍정적 반응을 보인 자가 주택 보유자"

**구현 파일**: `app/agents/customer_agent.py`

---

### Agent 2: 베스트뱅커 규정 질의응답 에이전트

**목적**: 베스트뱅커 규정집(RAG) 기반으로 사용자의 규정 관련 질문에 답변

**입력**: 자유 형식 질문 (str)

**처리 흐름**:
```
사용자 질문
  → search_best_banker_regulations(query)
      └─ Elasticsearch `edu-collection` BM25 검색 (top-5 문서)
  → 검색 문서 + 질문 → LLM 답변 생성
  → 출처 근거 포함 반환
```

**신규 Tool**:
```python
@tool
def search_best_banker_regulations(query: str) -> str:
    """베스트뱅커 규정집(edu-collection)에서 관련 내용을 BM25로 검색합니다."""
```
- 기존 `_build_retriever()` 패턴 재사용, 인덱스명 `edu-collection`

**구현 파일**: `app/agents/regulation_agent.py`

---

### Agent 3: 베스트뱅커 현황 파악 에이전트

**목적**: 직원번호 기반으로 수신/여신/전자금융 3개 상품군별 현황 및 부족 상품군 제시

**입력**: `employee_id` (TEXT, 예: `"EMP007"`)

**처리 흐름**:
```
employee_id 입력
  → get_banker_dashboard(employee_id)
      └─ best_banker_status에서 deposit_score, loan_score, digital_score, total_score 조회
  → get_group_statistics()
      └─ best_banker_status 전체에서 상품군별 10위 점수, 중앙값 계산
  → get_worst_group(employee_id)
      └─ 3개 상품군 중 10위 컷 대비 격차가 가장 큰 상품군 반환
  → LLM: 현황 리포트 + 개선 제안 생성
```

**신규 Tool**:
```python
@tool
def get_banker_dashboard(employee_id: str) -> str:
    """직원의 best_banker_status를 조회하여 수신/여신/전자금융 점수와 합계를 반환합니다."""

@tool
def get_group_statistics() -> str:
    """best_banker_status 전체 데이터에서 수신/여신/전자금융 각 상품군의 10위 점수와 중앙값을 계산하여 반환합니다."""

@tool
def get_worst_group(employee_id: str) -> str:
    """직원의 3개 상품군 점수와 전체 10위 컷을 비교하여, 격차가 가장 큰 상품군(1/2/3)과 이름을 반환합니다."""
```

**출력 형식**:
```
📊 베스트뱅커 현황 리포트 (직원번호: EMP007)
마지막 집계: 2025-03-20 09:00:00
──────────────────────────────────────────────────
상품군       | 내 점수 | 10위 컷 | 중앙값 | 격차
수신(예적금)  |  142.5  |  180.0  | 155.3  |  -37.5  ← 가장 부족
여신(대출)    |  195.0  |  210.0  | 188.7  |  -15.0
전자금융      |  88.0   |   95.0  |  82.1  |   -7.0
합계          |  425.5  |    —    |   —    |
──────────────────────────────────────────────────
💡 가장 부족한 상품군: 수신(예적금) — 10위 컷까지 37.5점 부족
```

**구현 파일**: `app/agents/dashboard_agent.py`

---

### Agent 4: 상품 추천 에이전트

**목적**: 고객번호 유무에 따라 분기하여 최적 상품을 추천하고 마케팅 문구 생성

**입력**: `employee_id` (str), `customer_id` (str | None)

#### 경로 A: 고객번호 있을 때

```
사용자 발화 + customer_id
  → [의도 파악] LLM 분류
      │
      ├─ 고객 중심 추천
      │    → get_top_product_for_customer(customer_id)
      │        └─ product_recommendation에서 추천 점수 최고 상품
      │    → summarize_customer(customer_id)   ← Agent 1 tool 재사용
      │    → LLM: 고객 요약 + 상품 → 마케팅 문구 생성
      │
      └─ 베스트뱅커 추진용
           → get_worst_group(employee_id)      ← Agent 3 tool 재사용
           → get_top_product_for_customer(customer_id, product_group_code=worst_group)
               ├─ 해당 상품군 추천 있음 → 최고 점수 상품 선택 → 마케팅 문구
               └─ 없음 → 고객 중심 추천으로 폴백
```

**신규 Tool (경로 A)**:
```python
@tool
def get_top_product_for_customer(customer_id: str, product_group_code: int = None) -> str:
    """product_recommendation에서 추천 점수가 가장 높은 상품을 반환합니다.
    product_group_code 지정 시 해당 상품군(1:수신, 2:여신, 3:전자금융) 내 최고 점수 상품."""

@tool
def generate_marketing_message(customer_summary: str, product_name: str, product_group: str) -> str:
    """고객 요약과 추천 상품 정보를 기반으로 마케팅 문구를 생성합니다."""
```

#### 경로 B: 고객번호 없을 때

```
employee_id만 존재
  → get_worst_group(employee_id)            ← 부족한 상품군 확인
  → get_promoted_customers(employee_id)
      └─ best_banker_promotion에서 해당 직원이 추진한 고객 목록 조회
  → get_most_pushed_product_in_group(customer_ids, product_group_code)
      └─ product_recommendation에서 해당 상품군 내 가장 많이 추천된 상품 선택
  → 해당 상품이 추천된 고객별 summarize_customer() 결과 반환
```

**신규 Tool (경로 B)**:
```python
@tool
def get_promoted_customers(employee_id: str) -> str:
    """best_banker_promotion에서 해당 직원이 추진 이력이 있는 고객 ID 목록을 반환합니다."""

@tool
def get_most_pushed_product_in_group(customer_ids: list[str], product_group_code: int) -> str:
    """주어진 고객 목록의 product_recommendation에서 특정 상품군 내 가장 많이 추천된 상품과 해당 고객 목록을 반환합니다."""
```

**구현 파일**: `app/agents/recommendation_agent.py`

---

### Agent 5: 베스트뱅커 시뮬레이션 에이전트

**목적**: 상품 추진 시 예상 점수 변화를 규정집 기반으로 계산하여 시뮬레이션

**입력**: `employee_id` (str), `product_code` (str)

**처리 흐름**:
```
employee_id + product_code 입력
  → get_score_config(product_code)
      └─ banker_score_config에서 product_group_code, add_score 조회
  → get_banker_dashboard(employee_id)   ← Agent 3 tool 재사용
      └─ 현재 수신/여신/전자금융/합계 점수
  → simulate_score_change(employee_id, product_code)
      └─ 해당 상품군 점수 + add_score 계산, 전체 순위 재계산
  → search_best_banker_regulations(product_code 관련 쿼리)
      └─ RAG: 해당 상품/상품군의 가점 조건, 상한선, 예외 규정 검색
  → LLM: 시뮬레이션 결과 + 규정 근거 종합 리포트 생성
```

**신규 Tool**:
```python
@tool
def get_score_config(product_code: str) -> str:
    """banker_score_config에서 상품코드의 상품군과 가점을 반환합니다."""

@tool
def simulate_score_change(employee_id: str, product_code: str) -> str:
    """현재 점수에 add_score를 더해 상품군별/합계 예상 점수와 순위 변화를 계산합니다."""
```

**출력 형식**:
```
🎯 베스트뱅커 시뮬레이션 (직원: EMP007 / 상품: DEP101)
────────────────────────────────────────────────────────
상품명       : 정기예금 플러스
상품군       : 수신(예적금) (group 1)
부여 가점    : +12.5점

          현재        → 추진 후
수신 점수 | 142.5점   →  155.0점
합계 점수 | 425.5점   →  438.0점
전체 순위 | 12위       →  9위 (▲3위)

📋 규정 근거 (edu-collection 검색 결과):
"정기예금 가입 건당 12.5점 부여, 동일 고객 월 1회 한정..." (§4.1)

⚠️ 유의사항: 규정집의 조건 및 예외사항을 반드시 확인하세요.
```

**구현 파일**: `app/agents/simulation_agent.py`

---

## 공통 구현 패턴

### 에이전트 팩토리 구조

```python
# app/agents/<name>_agent.py

def create_<name>_agent(model, checkpointer):
    tools = [tool_a, tool_b, ...]
    agent = create_react_agent(
        model=model.bind_tools(tools),
        tools=tools,
        checkpointer=checkpointer,
    )
    return agent
```

### ChatResponse 응답 형식

`agent_service.py` 파싱 로직과 호환되도록 모든 에이전트 최종 응답은 `ChatResponse` tool call:

```json
{
  "message_id": "<UUID>",
  "content": "<최종 응답 텍스트>",
  "metadata": {}
}
```

---

## Tool 전체 목록

### 신규 구현

| Tool | 사용 에이전트 | 참조 테이블 |
|------|-------------|------------|
| `get_customer_raw_data(customer_id)` | Agent 1 | customer_basic, customer_profile, customer_consultation |
| `summarize_customer(customer_id)` | Agent 1, 4 | 위 3개 + LLM |
| `search_best_banker_regulations(query)` | Agent 2, 5 | ES edu-collection |
| `get_banker_dashboard(employee_id)` | Agent 3, 4, 5 | best_banker_status |
| `get_group_statistics()` | Agent 3 | best_banker_status 전체 |
| `get_worst_group(employee_id)` | Agent 3, 4 | best_banker_status 전체 |
| `get_top_product_for_customer(customer_id, group?)` | Agent 4A | product_recommendation |
| `generate_marketing_message(summary, product, group)` | Agent 4 | LLM |
| `get_promoted_customers(employee_id)` | Agent 4B | best_banker_promotion |
| `get_most_pushed_product_in_group(customer_ids, group)` | Agent 4B | product_recommendation |
| `get_score_config(product_code)` | Agent 5 | banker_score_config |
| `simulate_score_change(employee_id, product_code)` | Agent 5 | best_banker_status, banker_score_config |

---

## 파일 구조

```
app/
├── agents/
│   ├── __init__.py
│   ├── tools.py                  ← 전체 tool 함수 정의
│   ├── prompts.py                ← 에이전트별 시스템 프롬프트
│   ├── customer_agent.py         ← Agent 1
│   ├── regulation_agent.py       ← Agent 2
│   ├── dashboard_agent.py        ← Agent 3
│   ├── recommendation_agent.py   ← Agent 4
│   ├── simulation_agent.py       ← Agent 5
│   └── banking_agent.py          ← 슈퍼바이저 (라우팅)
├── data/
│   ├── banking.db                ← 신규 DB
│   └── create_mock_data.py       ← 가상 데이터 생성 스크립트
└── services/
    └── agent_service.py          ← banking_agent 연결
```

---

## 구현 순서

| 단계 | 작업 | 선행 조건 |
|------|------|---------|
| 1 | `banking.db` 스키마 생성 + `create_mock_data.py` 작성 | `product_recommendation` 스키마 수령 |
| 2 | **Agent 1** — 고객 정보 요약 | DB 생성 |
| 3 | **Agent 2** — 규정 QA | ES 연결 확인 |
| 4 | **Agent 3** — 현황 파악 | DB 생성 |
| 5 | **Agent 5** — 시뮬레이션 | Agent 2, 3 완료 |
| 6 | **Agent 4A** — 상품 추천 (고객번호 있음) | Agent 1, 3 완료 |
| 7 | **Agent 4B** — 상품 추천 (고객번호 없음) | Agent 4A + DB 완성 |
| 8 | **슈퍼바이저** `banking_agent.py` | 전 에이전트 완료 |
| 9 | `agent_service.py` 연결 + 통합 테스트 | 단계 8 완료 |

---

## 추천 점수 활용 방식

`recommend_score`는 1~1000 정수형으로 높을수록 해당 고객에게 유망한 상품.

- **Agent 4A 고객중심**: `WHERE customer_id = ? ORDER BY recommend_score DESC LIMIT 1`
- **Agent 4A 베스트뱅커**: `WHERE customer_id = ? AND product_group_code = ? ORDER BY recommend_score DESC LIMIT 1`
- **Agent 4B**: 담당 고객 전체 대상 특정 상품군 내 `GROUP BY product_code COUNT(*)` 가장 많이 추천된 상품 선택
