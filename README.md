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
  DB Query   ES (BM25/term)    DB Query     DB Query    DB Query + ES
   고객정보   베스트뱅커규정    성과대시보드  상품추천    시뮬레이션
```

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
- 60여 개 상품 (4개 카테고리)
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

## 📋 5개 Sub-Agent 상세

각 에이전트는 `create_react_agent(model, tools, prompt, checkpointer=None)`로 생성되며, Supervisor가 사용자 의도에 따라 라우팅합니다.

### Agent 1 · Customer Agent

| 항목 | 내용 |
|------|------|
| **라우팅 조건** | "CUST001 고객 알려줘", "고객 정보 요약해줘" 등 고객번호 언급 또는 고객 조회 요청 |
| **사용 도구** | `get_customer_raw_data`, `summarize_customer` |
| **프롬프트 전략** | 고객번호를 받아 3개 테이블을 조회한 뒤 마케팅 관점의 한 문장 요약 생성 |
| **출력** | 자연어 한 문장 요약 (잔액, 서비스 가입 현황, 상담 이력, 마케팅 동의 반영) |

### Agent 2 · Regulation Agent

| 항목 | 내용 |
|------|------|
| **라우팅 조건** | "수신 평가배점이 얼마야", "실적인정기준 알려줘" 등 베스트뱅커 규정 질의 |
| **사용 도구** | `get_regulation_section` (정확 조회), `search_best_banker_regulations` (키워드 검색) |
| **프롬프트 전략** | 질문 유형에 따라 도구를 선택: 상품군/섹션이 명확하면 term filter, 불명확하면 BM25 |
| **출력** | 규정 근거를 인용한 한국어 답변, 금액은 한글 → 숫자 변환 |

**도구 선택 가이드:**

| 질문 유형 | 사용 도구 | 파라미터 예시 |
|---|---|---|
| "수신 실적산출 대상 상품" | `get_regulation_section` | section=수신, subsection=실적산출대상 |
| "평가배점 최대 점수" | `get_regulation_section` | section=수신, subsection=평가배점 |
| "득점기준 알려줘" | `get_regulation_section` | section=수신, subsection=평점산출방식 |
| 상품군 불명확한 자유 검색 | `search_best_banker_regulations` | query=키워드 |

### Agent 3 · Dashboard Agent

| 항목 | 내용 |
|------|------|
| **라우팅 조건** | "내 성과 분석해줘", "EMP001 현황 보여줘" 등 직원 성과/순위 조회 |
| **사용 도구** | `get_banker_dashboard`, `get_group_statistics`, `get_worst_group` |
| **프롬프트 전략** | 직원번호는 세션에서 자동 추출 → 3개 도구를 순서대로 호출하여 비교 리포트 작성 |
| **출력** | 상품군별 점수 비교표 (내 점수 / TOP10 / 중앙값 / 격차) + 부족 상품군 + 개선 조언 |

### Agent 4 · Recommendation Agent

| 항목 | 내용 |
|------|------|
| **라우팅 조건** | "상품 추천해줘", "어떤 상품 팔면 좋아" 등 상품 추천 요청 |
| **사용 도구** | `get_worst_group`, `get_top_product_for_customer`, `summarize_customer`, `generate_marketing_message`, `get_promoted_customers`, `get_most_pushed_product_in_group` |
| **프롬프트 전략** | 고객번호 유무에 따라 3가지 경로로 분기 (아래 참조) |
| **출력** | TOP3 상품 + 고객 특성 제시 → 은행원 선택 → 담백한 마케팅 문구 생성 |

**추천 경로 분기:**

```
고객번호(CUST###) 있음?
    Yes → "고객 중심 추천인가요, 베스트뱅커 추진용인가요?" 질문
            ├─ A-1 고객 중심:
            │    get_top_product_for_customer(top_n=3)
            │    → summarize_customer
            │    → TOP3 + 고객 특성 출력 후 선택 대기
            │    → generate_marketing_message(선택 상품)
            │
            └─ A-2 베스트뱅커 추진용:
                 get_worst_group → get_top_product_for_customer(category=부족군, top_n=3)
                 → summarize_customer
                 → TOP3 + 고객 특성 출력 후 선택 대기
                 → generate_marketing_message(선택 상품)

    No  → 안내 메시지 출력 후 선택 대기
            ├─ 고객번호 제공 → A-1/A-2 진입
            └─ 베스트뱅커 실적 관점 선택 → 경로 B:
                 get_worst_group → get_promoted_customers
                 → get_most_pushed_product_in_group(customer_ids, category=부족군)
                 → summarize_customer (matched_customers 각각)
```

### Agent 5 · Simulation Agent

| 항목 | 내용 |
|------|------|
| **라우팅 조건** | "정기예금 팔면 점수 얼마 올라?", "NH전세대출 득점기준 알려줘" 등 상품 추진 시 득점 안내 |
| **사용 도구** | `get_banker_dashboard`, `get_product_info`, `get_regulation_section`, `search_best_banker_regulations` |
| **프롬프트 전략** | 직원 현재 점수 → 상품 정보 확인 → 평점산출방식 조회 → 실적인정기준 조회 → 결과 출력 |
| **출력** | 현재 점수 섹션 + 득점기준 섹션(평점산출방식 기준) + 실적인정기준 섹션(별도 참고) |

**시뮬레이션 5단계 흐름:**
1. `get_banker_dashboard(employee_id)` — 현재 4개 상품군 점수 조회
2. `get_product_info(product_name)` — 카테고리, 세부분류 확인
3. `get_regulation_section(section, subsection="평점산출방식")` — 득점기준 조회 (fallback: 득점기준)
4. `get_regulation_section(section, subsection="실적인정기준")` — 실적인정 조건 조회 (별도 표시용)
5. 현재 점수 + 득점기준 + 실적인정기준 통합 출력

---

## 🔧 도구(Tools) 상세

총 12개 도구 (`app/agents/tools.py`)

### 고객 정보 도구

#### `get_customer_raw_data(customer_id)`
| 항목 | 내용 |
|------|------|
| **파라미터** | `customer_id: str` — CUST001 형식 |
| **조회 테이블** | customer_basic, customer_profile, customer_consultation |
| **반환** | `{"basic": {...}, "profile": {...}, "consultations": [...]}` |
| **사용 에이전트** | Customer (Agent 1), Recommendation (Agent 4) |

#### `summarize_customer(customer_id)`
| 항목 | 내용 |
|------|------|
| **파라미터** | `customer_id: str` |
| **내부 동작** | `get_customer_raw_data` 호출 → LLM (temperature=0.3) 요약 |
| **반환** | 마케팅 관점 한 문장 요약 (마케팅 동의, 상담 반응 -1/0/1 반영) |
| **사용 에이전트** | Customer (Agent 1), Recommendation (Agent 4) |

### 규정 검색 도구

#### `search_best_banker_regulations(query)`
| 항목 | 내용 |
|------|------|
| **파라미터** | `query: str` — 자유 키워드 |
| **검색 방식** | Elasticsearch BM25 (bestbanker-2025 인덱스, top_k=5) |
| **반환** | 상위 결과 텍스트 (최대 1500자/문서) |
| **사용 에이전트** | Regulation (Agent 2), Simulation (Agent 5) |

#### `get_regulation_section(section, subsection=None)`
| 항목 | 내용 |
|------|------|
| **파라미터** | `section: str` — 수신\|개인여신\|기업여신\|디지털금융<br>`subsection: str` (선택) — 평가배점\|실적산출대상\|평점산출방식\|득점기준\|실적인정기준\|실적제외대상\|담당자 |
| **검색 방식** | Elasticsearch term filter (keyword 필드 정확 매칭) |
| **반환** | 해당 규정 문서 텍스트 (최대 2000자/문서) |
| **사용 에이전트** | Regulation (Agent 2), Simulation (Agent 5) |

### 직원 성과 도구

#### `get_banker_dashboard(employee_id)`
| 항목 | 내용 |
|------|------|
| **파라미터** | `employee_id: str` — EMP001 형식 |
| **조회 테이블** | best_banker_status |
| **반환** | `{"deposit_score": N, "personal_loan_score": N, "corporate_loan_score": N, "digital_score": N, "total_score": N}` |
| **사용 에이전트** | Dashboard (Agent 3), Recommendation (Agent 4), Simulation (Agent 5) |

#### `get_group_statistics()`
| 항목 | 내용 |
|------|------|
| **파라미터** | 없음 |
| **조회 테이블** | best_banker_status (전체) |
| **반환** | 상품군별 `{"top10_score": N, "median_score": N, "total_members": N}` |
| **사용 에이전트** | Dashboard (Agent 3) |

#### `get_worst_group(employee_id)`
| 항목 | 내용 |
|------|------|
| **파라미터** | `employee_id: str` |
| **조회 테이블** | best_banker_status |
| **반환** | `{"worst_category": "수신", "gap_to_top10": -42.3, "all_gaps": {...}}` |
| **사용 에이전트** | Dashboard (Agent 3), Recommendation (Agent 4), Simulation (Agent 5) |

### 상품 추천 도구 (고객번호 있을 때)

#### `get_top_product_for_customer(customer_id, category=None, top_n=1)`
| 항목 | 내용 |
|------|------|
| **파라미터** | `customer_id: str`<br>`category: str` (선택) — 수신\|개인여신\|기업여신\|디지털금융<br>`top_n: int` (기본=1, 최대=10) |
| **조회 테이블** | product_recommendation JOIN product_master |
| **반환** | top_n=1: 단일 상품 dict<br>top_n>1: `{"count": N, "results": [{"rank": 1, "product_name": ..., "recommend_score": N}]}` |
| **사용 에이전트** | Recommendation (Agent 4) |

#### `generate_marketing_message(customer_summary, product_name, product_group_name)`
| 항목 | 내용 |
|------|------|
| **파라미터** | `customer_summary: str` — summarize_customer 결과<br>`product_name: str`<br>`product_group_name: str` — 카테고리명 |
| **내부 동작** | LLM (temperature=0.7), 담백하고 근거 있는 2문장 이내 문구 생성 |
| **반환** | 은행원이 고객에게 실제로 말할 수 있는 영업 문구 |
| **사용 에이전트** | Recommendation (Agent 4) |

### 상품 추천 도구 (고객번호 없을 때)

#### `get_promoted_customers(employee_id)`
| 항목 | 내용 |
|------|------|
| **파라미터** | `employee_id: str` |
| **조회 테이블** | best_banker_promotion |
| **반환** | `{"customer_ids": ["CUST001", ...], "count": N}` |
| **사용 에이전트** | Recommendation (Agent 4) |

#### `get_most_pushed_product_in_group(customer_ids, category)`
| 항목 | 내용 |
|------|------|
| **파라미터** | `customer_ids: list[str]` — get_promoted_customers 결과<br>`category: str` — 수신\|개인여신\|기업여신\|디지털금융 |
| **조회 테이블** | product_recommendation, customer_basic, product_master |
| **반환** | `{"product_name": ..., "category": ..., "matched_customers": [{"customer_id": ..., "recommend_score": N}]}` |
| **사용 에이전트** | Recommendation (Agent 4) |

### 시뮬레이션 도구

#### `get_product_info(product_name)`
| 항목 | 내용 |
|------|------|
| **파라미터** | `product_name: str` — 상품명 또는 일부 (LIKE 검색) |
| **조회 테이블** | product_master |
| **반환** | `{"results": [{"product_id": ..., "category": ..., "sub_category": ..., "regulation_code": ...}]}` |
| **사용 에이전트** | Simulation (Agent 5) |

---

## 🗄️ 데이터베이스 구조

SQLite 7개 테이블 (`app/data/banking.db`)

### 테이블 스키마

#### customer_basic (50행)
| 컬럼 | 타입 | 설명 |
|------|------|------|
| `customer_id` | TEXT PK | CUST001~CUST050 |
| `customer_name` | TEXT | 고객 이름 |
| `deposit_balance` | REAL | 예금 잔액 (100,000~50,000,000) |
| `loan_balance` | REAL | 대출 잔액 (0~30,000,000) |
| `is_mobile_banking_active` | INTEGER | 모바일뱅킹 활성 여부 (0/1) |
| `is_open_banking_joined` | INTEGER | 오픈뱅킹 가입 여부 (0/1) |
| `is_mydata_joined` | INTEGER | 마이데이터 가입 여부 (0/1) |
| `has_salary_transfer` | INTEGER | 급여이체 여부 (0/1) |
| `has_utility_auto_transfer` | INTEGER | 공과금 자동이체 여부 (0/1) |
| `is_marketing_agreed` | INTEGER | 마케팅 동의 여부 (0/1) |

#### customer_profile (50행)
| 컬럼 | 타입 | 설명 |
|------|------|------|
| `customer_id` | TEXT PK, FK | customer_basic 참조 |
| `is_married_estimated` | INTEGER | 추정 결혼 여부 (0/1) |
| `has_car_estimated` | INTEGER | 추정 차량 보유 여부 (0/1) |
| `has_children_estimated` | INTEGER | 추정 자녀 여부 (0/1) |
| `is_homeowner_estimated` | INTEGER | 추정 주택 소유 여부 (0/1) |
| `avg_weekend_spend_count` | INTEGER | 주말 평균 지출 건수 (0~15) |
| `avg_night_spend_count` | INTEGER | 야간 평균 지출 건수 (0~8) |
| `last_contact_elapsed_days` | INTEGER | 마지막 접촉 후 경과일 (0~180) |

#### customer_consultation (고객당 2~4건)
| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | INTEGER PK | 자동증가 |
| `customer_id` | TEXT FK | customer_basic 참조 |
| `product_id` | TEXT FK | product_master 참조 |
| `product_name` | TEXT | 상품명 |
| `interaction_result` | INTEGER | 상담 반응: 1(긍정), 0(중립), -1(부정) |
| `consulted_at` | TEXT | 상담 일시 |

#### product_master (60여 개 상품)
| 컬럼 | 타입 | 설명 |
|------|------|------|
| `product_id` | TEXT PK | 8자리 코드 (CC PP SSSS) |
| `category` | TEXT | 수신 \| 개인여신 \| 기업여신 \| 디지털금융 |
| `sub_category` | TEXT | 세부 분류 (핵심예금, MMDA, 전세자금 등) |
| `product_name` | TEXT | 상품명 |
| `regulation_code` | TEXT | 규정집 원본 코드 (nullable) |
| `is_active` | INTEGER | 활성 여부 (0/1) |

**상품 코드 체계:** `CC PP SSSS` — CC(카테고리: 01=수신, 02=개인여신, 03=기업여신, 04=디지털금융), PP(부분류), SSSS(순번)

#### best_banker_status (20행)
| 컬럼 | 타입 | 설명 |
|------|------|------|
| `employee_id` | TEXT PK | EMP001~EMP020 |
| `deposit_score` | REAL | 수신 점수 (50~250) |
| `personal_loan_score` | REAL | 개인여신 점수 (30~200) |
| `corporate_loan_score` | REAL | 기업여신 점수 (30~200) |
| `digital_score` | REAL | 디지털금융 점수 (20~100) |
| `total_score` | REAL | 합계 점수 |
| `last_updated` | TEXT | 최종 업데이트 일시 |

#### best_banker_promotion (80행)
| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | INTEGER PK | 자동증가 |
| `employee_id` | TEXT FK | best_banker_status 참조 |
| `customer_id` | TEXT FK | customer_basic 참조 |
| `category` | TEXT | 상품 카테고리 |
| `product_id` | TEXT FK | product_master 참조 |
| `promotion_date` | TEXT | 추진 일시 |

#### product_recommendation (고객당 카테고리별 2~5개)
| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | INTEGER PK | 자동증가 |
| `customer_id` | TEXT FK | customer_basic 참조 |
| `category` | TEXT | 상품 카테고리 |
| `product_id` | TEXT FK | product_master 참조 |
| `recommend_score` | INTEGER | 추천 점수 (1~1000) |

### 테이블 관계

```
customer_basic ──┬── customer_profile          (1:1, customer_id)
                 ├── customer_consultation      (1:N, customer_id)
                 ├── best_banker_promotion      (1:N, customer_id)
                 └── product_recommendation     (1:N, customer_id)

product_master ──┬── customer_consultation      (1:N, product_id)
                 ├── best_banker_promotion      (1:N, product_id)
                 └── product_recommendation     (1:N, product_id)

best_banker_status ── best_banker_promotion     (1:N, employee_id)
```

### 상품군 코드 매핑

| DB 카테고리값 | 에이전트 파라미터 | best_banker_status 컬럼 |
|---|---|---|
| 수신 | 수신 | deposit_score |
| 개인여신 | 개인여신 | personal_loan_score |
| 기업여신 | 기업여신 | corporate_loan_score |
| 디지털금융 | 디지털금융 | digital_score |

---

## 🔗 에이전트 ↔ 도구 ↔ 데이터 연결 맵

```
Customer Agent
  └─ get_customer_raw_data  → customer_basic + customer_profile + customer_consultation
  └─ summarize_customer     → (get_customer_raw_data 내부 호출) → LLM temperature=0.3

Regulation Agent
  └─ get_regulation_section        → ES bestbanker-2025 (term filter, 정확 매칭)
  └─ search_best_banker_regulations → ES bestbanker-2025 (BM25, 자유 검색)

Dashboard Agent
  └─ get_banker_dashboard   → best_banker_status (단일 직원)
  └─ get_group_statistics   → best_banker_status (전체 직원, TOP10/중앙값 계산)
  └─ get_worst_group        → best_banker_status (단일 직원 + 전체 비교 → 격차 최대 카테고리)

Recommendation Agent
  └─ get_worst_group                   → best_banker_status
  └─ get_top_product_for_customer      → product_recommendation JOIN product_master
  └─ summarize_customer                → customer_basic + customer_profile + customer_consultation → LLM
  └─ generate_marketing_message        → LLM temperature=0.7 (문구 생성)
  └─ get_promoted_customers            → best_banker_promotion
  └─ get_most_pushed_product_in_group  → product_recommendation + customer_basic + product_master

Simulation Agent
  └─ get_banker_dashboard         → best_banker_status
  └─ get_product_info             → product_master (LIKE 검색)
  └─ get_regulation_section       → ES bestbanker-2025 (평점산출방식, 실적인정기준)
  └─ search_best_banker_regulations → ES bestbanker-2025 (BM25 fallback)
```

---

## 🔍 Elasticsearch 인덱스 구조

인덱스명: `bestbanker-2025` (27개 문서)

| 필드 | 타입 | 값 예시 |
|------|------|---------|
| `section` | keyword | 수신, 개인여신, 기업여신, 디지털금융 |
| `subsection` | keyword | 평가배점, 실적산출대상, 평점산출방식, 득점기준, 실적인정기준, 실적제외대상, 담당자 |
| `content_type` | keyword | — |
| `text` | text | 규정 본문 |

**검색 방식 비교:**

| 도구 | 검색 방식 | 적합한 상황 |
|------|----------|------------|
| `get_regulation_section` | term filter (exact match) | 상품군/섹션 유형이 명확할 때 |
| `search_best_banker_regulations` | BM25 full-text | 자유 키워드, 상품군 불명확할 때 |

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
# 전체 테스트 실행 (35개)
uv run pytest

# 커버리지 리포트
uv run pytest --cov=app tests/ --cov-report=term-missing

# 특정 테스트 실행
uv run pytest tests/test_tools.py -v
```

| 파일 | 테스트 수 | 대상 |
|---|---|---|
| `test_main.py` | 2 | 루트/헬스 엔드포인트 |
| `test_mock_db.py` | 8 | Mock DB API (SQL Injection 검증 포함) |
| `test_tools.py` | 13 | 12개 도구 함수 (LLM 모킹 포함) |
| `test_agent_service.py` | 7 | AgentService 스트리밍/에러 처리 |
| `test_chat.py` | 5 | Chat 라우트 SSE 스트리밍 |

---

## 📌 주요 특징

1. **Supervisor 기반 라우팅**: LLM이 사용자 의도를 분석하여 적절한 sub-agent 선택
2. **세션 컨텍스트 주입**: 대화 이력에서 직원번호(`EMP\d+`)를 추출하여 자동으로 세션 정보 전달
3. **SSE 스트리밍**: 도구 호출 과정을 실시간으로 클라이언트에 전송
4. **Sub-Agent 내부 추적**: `subgraphs=True` 옵션으로 각 에이전트 내부 단계(model/tools)까지 시각화
5. **하이브리드 검색**: SQLite (구조화 데이터) + Elasticsearch (전문 검색, BM25 + term filter)
6. **2단계 추천 흐름**: TOP3 제시 → 선택 → 담백한 마케팅 문구 생성

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
│   ├── test_main.py
│   ├── test_mock_db.py
│   ├── test_tools.py
│   ├── test_agent_service.py
│   └── test_chat.py
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

## 🛠️ 개발 팁

### 1. 새 에이전트 추가

1. `app/agents/<name>_agent.py` 생성
2. `app/agents/prompts.py`에 시스템 프롬프트 추가
3. `app/agents/banking_agent.py`의 supervisor에 노드 추가
4. `app/services/agent_service.py`의 `_BANKING_SUB_AGENTS` set에 이름 추가

### 2. 새 도구 추가

1. `app/agents/tools.py`에 `@tool` 데코레이터로 함수 작성
2. 해당 에이전트의 `tools` 리스트에 추가
3. 도구 docstring은 LLM이 사용법을 이해할 수 있도록 명확하게 작성

### 3. Elasticsearch 연결 테스트

```bash
uv run python test_es.py
```

### 4. 로깅

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
