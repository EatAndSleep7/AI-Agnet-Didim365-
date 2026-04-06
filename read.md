# 베스트뱅커 멀티 에이전트 시스템 — 서브 에이전트 · 툴 · 프롬프트 상세 가이드

## 시스템 구조 개요

```
사용자 메시지
  └─ Supervisor (banking_agent.py)
       ├─ customer_agent       고객 정보 조회 · 요약
       ├─ regulation_agent     규정집 Q&A
       ├─ dashboard_agent      베스트뱅커 현황 분석
       ├─ recommendation_agent 상품 추천 · 마케팅 문구
       ├─ strategy_agent       추진 전략 수립 (결정론적 Python)
       └─ simulation_agent     상품별 예상 점수 시뮬레이션
```

Supervisor는 `model.with_structured_output(RouteOutput)`으로 LLM이 6개 에이전트 중 하나를 선택하게 한 뒤, `Command(goto=route)` 로 라우팅합니다. 대화 이력에서 `EMP\d+` 패턴으로 직원번호를 추출해 `[세션 직원번호] EMPXXX` SystemMessage를 자동 삽입합니다.

---

## 1. 서브 에이전트 상세

### 1-1. customer_agent

**파일:** `app/agents/customer_agent.py`
**타입:** `create_react_agent` (ReAct)
**도구:** `get_customer_raw_data`, `summarize_customer`
**프롬프트:** `CUSTOMER_SUMMARY_SYSTEM_PROMPT`

고객번호(`CUST`로 시작)가 명시된 경우 3개 테이블(`customer_basic`, `customer_profile`, `customer_consultation`)을 조회하여 한 문장으로 요약합니다. `summarize_customer` 하나로 조회+요약이 모두 처리됩니다.

---

### 1-2. regulation_agent

**파일:** `app/agents/regulation_agent.py`
**타입:** `create_react_agent` (ReAct)
**도구:** `get_regulation_section`, `search_best_banker_regulations`
**프롬프트:** `REGULATION_QA_SYSTEM_PROMPT`

Elasticsearch `bestbanker-2025` 인덱스(27개 문서)를 대상으로 규정집을 검색합니다.

- 상품군(`section`)과 항목(`subsection`)이 명확하면 `get_regulation_section` 우선 사용 (정확한 term query)
- 키워드만 있거나 상품군이 불분명하면 `search_best_banker_regulations` (BM25 자유 검색)

섹션 분류:

| section | subsection 예시 |
|---|---|
| 수신 / 개인여신 / 기업여신 / 디지털금융 | 평가배점, 실적산출대상, 평점산출방식, 득점기준, 실적인정기준, 실적제외대상, 담당자 |

---

### 1-3. dashboard_agent

**파일:** `app/agents/dashboard_agent.py`
**타입:** `create_react_agent` (ReAct)
**도구:** `get_banker_dashboard`, `get_group_statistics`, `get_worst_group`
**프롬프트:** `BANKER_DASHBOARD_SYSTEM_PROMPT`

직원의 상품군별 점수를 전체 TOP10/중앙값과 비교하는 리포트를 생성합니다.

출력 포맷:
1. 상품군별 비교표 (내 점수 / TOP10 / 중앙값 / 격차)
2. 가장 부족한 상품군 + TOP10까지의 차이
3. 개선 조언 한 줄

직원번호는 `[세션 직원번호]` SystemMessage에서 우선 확인하고, 없으면 대화 이력의 `EMP\d+`를 탐색합니다.

---

### 1-4. recommendation_agent

**파일:** `app/agents/recommendation_agent.py`
**타입:** 커스텀 StateGraph (ReAct sub-subgraph 포함)

#### 그래프 구조

```
START → classify → ask_direction → END
                 → path_a1       → END
                 → path_a2       → END
```

#### classify 노드 (결정론적 Python + LLM structured output)

```python
class IntentOutput(BaseModel):
    intent: Literal["A1", "A2"] | None
```

최근 메시지 4개를 `RECOMMEND_CLASSIFY_PROMPT`와 함께 `model.with_structured_output(IntentOutput)`에 전달하여 의도를 분류합니다.

| intent | 의미 | 다음 노드 |
|---|---|---|
| A1 | 고객 성향 중심 추천 | path_a1 |
| A2 | 직원 부족 상품군 기반 추천 | path_a2 |
| null | 의도 불명 | ask_direction |

`_extract_customer_id(messages)`: 메시지를 역순으로 순회하여 `CUST\d+` 패턴의 가장 최근 고객번호를 추출합니다.

#### ask_direction 노드 (LLM 없음, 고정 문구)

```
"고객 성향 중심으로 추천할까요(1번), 아니면 직원의 부족 상품군 위주로 추천할까요(2번)?"
```

#### path_a1 노드 (ReAct)

**도구:** `get_top_product_for_customer`, `summarize_customer`, `generate_marketing_message`
**프롬프트:** `RECOMMEND_PATH_A1_PROMPT`

호출 순서:
1. `get_top_product_for_customer(customer_id, top_n=3)` → TOP3 상품
2. `summarize_customer(customer_id)` → 고객 특성 요약
3. 사용자 상품 선택 대기
4. `generate_marketing_message(customer_summary, product_name, product_group_name)` → 마케팅 문구

#### path_a2 노드 (ReAct)

**도구:** `get_worst_group`, `get_top_product_for_customer`, `summarize_customer`, `generate_marketing_message`
**프롬프트:** `RECOMMEND_PATH_A2_PROMPT`

호출 순서:
1. `get_worst_group(employee_id)` → 부족 상품군 확인
2. `get_top_product_for_customer(customer_id, category=부족_상품군, top_n=3)`
   - `{"found": false}` 반환 시 → category 없이 재호출 (고객 성향 기반으로 전환)
3. `summarize_customer(customer_id)` → 고객 특성
4. 사용자 상품 선택 대기
5. `generate_marketing_message(...)` → 마케팅 문구

---

### 1-5. strategy_agent

**파일:** `app/agents/strategy_agent.py`
**타입:** 결정론적 StateGraph (단일 Python 노드, ReAct 없음)

#### 설계 배경

프롬프트 기반 ReAct 에이전트는 RLHF 특성으로 인해 고객 데이터를 받으면 전략 해설·조언·결론 등 불필요한 내용을 계속 생성합니다. 프롬프트로는 이 행동을 억제할 수 없으므로, **출력 자체를 Python이 생성하도록 구조를 전환**했습니다.

#### 구조

```
START → run_strategy → END
```

`run_strategy`는 단일 Python 함수로, LLM은 입력 파싱에만 사용됩니다.

```python
class StrategyInput(BaseModel):
    employee_id: str | None
    target_category: Literal["수신", "개인여신", "기업여신", "디지털금융"] | None
```

#### 실행 순서

```python
# 1. LLM structured output으로 employee_id, target_category 추출
parsed = model.with_structured_output(StrategyInput).invoke(
    [SystemMessage(content=_PARSE_PROMPT)] + messages[-6:]
)

# 2. target_category 없으면 부족 상품군으로 결정
if not target_category:
    worst = json.loads(get_worst_group.invoke({"employee_id": employee_id}))
    target_category = worst["worst_category"]

# 3. 직원 추진 고객 목록 조회
promo = json.loads(get_promoted_customers.invoke({"employee_id": employee_id}))

# 4. 해당 상품군에서 가장 많이 추천된 상품 조회
pushed = json.loads(get_most_pushed_product_in_group.invoke(
    {"customer_ids": promo["customer_ids"], "category": target_category}
))

# 5. 고객별 요약 + Python 템플릿으로 포맷팅
for c in pushed["matched_customers"]:
    summary = summarize_customer.invoke({"customer_id": c["customer_id"]})
    # Python 문자열로 블록 생성
```

#### 출력 포맷 (Python 템플릿)

```
{target_category} 상품군에서 상담 이력 고객들에게 가장 많이 추천된 상품은 **{product_name}**입니다.
해당 상품이 추천된 고객 N명을 안내해드립니다.

---
### {고객명}

**고객 정보 요약**
{summarize_customer 결과}

**추천 상품 및 점수**
{product_name} — 추천점수: N점
---
```

LLM이 최종 텍스트를 생성하지 않으므로 포맷 이탈이 구조적으로 불가능합니다.

---

### 1-6. simulation_agent

**파일:** `app/agents/simulation_agent.py`
**타입:** `create_react_agent` (ReAct)
**도구:** `get_banker_dashboard`, `get_product_info`, `get_regulation_section`, `search_best_banker_regulations`
**프롬프트:** `SIMULATION_SYSTEM_PROMPT`

특정 상품명이 언급될 때 다음 순서로 도구를 호출합니다:

1. `get_banker_dashboard(employee_id)` → 현재 4개 상품군 점수
2. `get_product_info(product_name)` → 카테고리, sub_category 확인
3. `get_regulation_section(section=<카테고리>, subsection="평점산출방식")` → 득점 공식 (없으면 "득점기준"으로 재시도)
4. `get_regulation_section(section=<카테고리>, subsection="실적인정기준")` → 실적 인정 조건 (없으면 생략)

**시뮬레이션 계산 예시:**
- "신나는직장인대출 1억 추진" + 공식 "우량신용 평잔 1백만원당 0.8점"
- → 100백만원 × 0.8점 = +80점 예상

---

## 2. 도구 (Tools) 상세

**파일:** `app/agents/tools.py`
**데이터베이스:** `app/data/banking.db` (SQLite, 7개 테이블)

### 고객 정보 도구

#### `get_customer_raw_data(customer_id: str) → str`

**사용 에이전트:** customer_agent, recommendation_agent
**DB 쿼리:** `customer_basic`, `customer_profile`, `customer_consultation` 3개 테이블 조인

```json
{
  "basic":         { "customer_id": "CUST001", "customer_name": "...", ... },
  "profile":       { "lifestyle": "...", "risk_tolerance": "...", ... },
  "consultations": [{ "product_name": "...", "interaction_result": 1, ... }]
}
```

고객번호가 없으면 `{"found": false, "message": "..."}` 반환.

---

#### `summarize_customer(customer_id: str) → str`

**사용 에이전트:** customer_agent, recommendation_agent, strategy_agent
**내부 동작:** `get_customer_raw_data` 호출 후 LLM(temperature=0.3)으로 한 문장 요약 생성

프롬프트 핵심:
- 마케팅 관점의 핵심만 담은 **한 문장**
- 마케팅 동의 여부 + 상담 반응(1:긍정, 0:중립, -1:부정) 반드시 반영
- 단순 나열 금지

반환값: 자연어 문자열 (JSON 아님)

---

### 규정 검색 도구

#### `search_best_banker_regulations(query: str) → str`

**사용 에이전트:** regulation_agent, simulation_agent
**검색 방식:** BM25 (Elasticsearch `match` query, operator=OR)
**반환:** 상위 `TOP_K`개 문서의 `page_content` 최대 1500자씩 연결

---

#### `get_regulation_section(section: str, subsection: str | None = None) → str`

**사용 에이전트:** regulation_agent, simulation_agent
**검색 방식:** Elasticsearch `term` query (정확한 필드 매칭)

| 파라미터 | 유효값 |
|---|---|
| section | 수신, 개인여신, 기업여신, 디지털금융 |
| subsection | 평가배점, 실적산출대상, 평점산출방식, 득점기준, 실적인정기준, 실적제외대상, 담당자 |

`subsection` 생략 시 해당 `section`의 모든 문서 반환.
없으면 `{"found": false, "message": "..."}` 반환.

---

### 직원 현황 도구

#### `get_banker_dashboard(employee_id: str) → str`

**사용 에이전트:** dashboard_agent, recommendation_agent, simulation_agent
**DB 테이블:** `best_banker_status`

```json
{
  "found": true,
  "employee_id": "EMP001",
  "deposit_score": 85.0,
  "personal_loan_score": 62.0,
  "corporate_loan_score": 91.0,
  "digital_score": 44.0,
  "total_score": 282.0,
  "last_updated": "2025-01-15"
}
```

---

#### `get_group_statistics() → str`

**사용 에이전트:** dashboard_agent
**파라미터:** 없음 (전체 직원 대상)

```json
{
  "수신":     { "top10_score": 120.0, "median_score": 78.5, "total_members": 20 },
  "개인여신": { "top10_score": 95.0,  "median_score": 55.2, "total_members": 20 },
  ...
}
```

---

#### `get_worst_group(employee_id: str) → str`

**사용 에이전트:** dashboard_agent, recommendation_agent, strategy_agent
**계산 방식:** (내 점수 − 전체 TOP10 점수) → 가장 음수 값이 큰 상품군

```json
{
  "worst_category": "디지털금융",
  "gap_to_top10": -76.0,
  "all_gaps": {
    "수신": -35.0, "개인여신": -33.0, "기업여신": -9.0, "디지털금융": -76.0
  }
}
```

---

### 추천 도구 (고객번호 있는 경우)

#### `get_top_product_for_customer(customer_id: str, category: str | None = None, top_n: int = 1) → str`

**사용 에이전트:** recommendation_agent
**DB 테이블:** `product_recommendation` JOIN `product_master`

- `top_n=1`: 단일 객체 반환
- `top_n>1`: `{"found": true, "count": N, "results": [...]}` 리스트 반환
- `category` 지정 시 해당 상품군 내에서만 검색

```json
{
  "found": true,
  "product_id": "PROD001",
  "product_name": "NH정기예금",
  "category": "수신",
  "sub_category": "정기예금",
  "recommend_score": 92
}
```

---

#### `generate_marketing_message(customer_summary: str, product_name: str, product_group_name: str) → str`

**사용 에이전트:** recommendation_agent
**LLM:** temperature=0.7
**반환:** 자연어 문자열 (2문장 이내 마케팅 문구)

프롬프트 핵심:
- 고객 실제 특성(잔액, 상담이력, 마케팅동의)을 반드시 근거로 사용
- `'맞춤형', '최적의', '완벽한'` 등 추상적 수식어 금지

---

### 추천 도구 (고객번호 없는 경우 — strategy_agent 포함)

#### `get_promoted_customers(employee_id: str) → str`

**사용 에이전트:** strategy_agent
**DB 테이블:** `best_banker_promotion`

```json
{
  "found": true,
  "customer_ids": ["CUST001", "CUST005", "CUST012"],
  "count": 3
}
```

---

#### `get_most_pushed_product_in_group(customer_ids: list[str] | str, category: str) → str`

**사용 에이전트:** strategy_agent
**동작:** `customer_ids` 중 `category`에서 가장 많이 추천된 상품(추천 건수 기준) 및 해당 고객 목록 반환

- `customer_ids`가 단일 문자열이면 자동으로 리스트 변환
- 최대 500개 제한 (과도한 IN절 방지)

```json
{
  "found": true,
  "product_id": "PROD003",
  "product_name": "신나는직장인대출",
  "category": "개인여신",
  "sub_category": "신용대출",
  "matched_customers": [
    { "customer_id": "CUST001", "customer_name": "홍길동", "recommend_score": 88 },
    { "customer_id": "CUST005", "customer_name": "김영희", "recommend_score": 72 }
  ]
}
```

---

### 시뮬레이션 도구

#### `get_product_info(product_name: str) → str`

**사용 에이전트:** simulation_agent
**DB 테이블:** `product_master` (LIKE 부분 검색, is_active=1, 최대 5개)

```json
{
  "found": true,
  "results": [
    {
      "product_id": "PROD003",
      "product_name": "신나는직장인대출",
      "category": "개인여신",
      "sub_category": "신용대출",
      "regulation_code": "LOAN-001"
    }
  ]
}
```

---

### 도구-에이전트 매핑 요약

| 도구 | customer | regulation | dashboard | recommend | strategy | simulation |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| get_customer_raw_data | ✓ | | | ✓ | | |
| summarize_customer | ✓ | | | ✓ | ✓ | |
| search_best_banker_regulations | | ✓ | | | | ✓ |
| get_regulation_section | | ✓ | | | | ✓ |
| get_banker_dashboard | | | ✓ | ✓ | | ✓ |
| get_group_statistics | | | ✓ | | | |
| get_worst_group | | | ✓ | ✓ | ✓ | |
| get_top_product_for_customer | | | | ✓ | | |
| generate_marketing_message | | | | ✓ | | |
| get_promoted_customers | | | | | ✓ | |
| get_most_pushed_product_in_group | | | | | ✓ | |
| get_product_info | | | | | | ✓ |

---

## 3. 프롬프트 상세

**파일:** `app/agents/prompts.py`

### CUSTOMER_SUMMARY_SYSTEM_PROMPT

**목적:** customer_agent에게 고객 조회 방법 안내

핵심 지시:
- `summarize_customer` 도구 하나로 충분함을 명시 (`get_customer_raw_data`는 원시 데이터 조회용)
- 한국어로 자연스럽게 요약

---

### REGULATION_QA_SYSTEM_PROMPT

**목적:** regulation_agent에게 도구 선택 기준 제시

핵심 지시:
- 상품군이 명확하면 `get_regulation_section` 우선
- 키워드 검색은 `search_best_banker_regulations`

도구 선택 가이드표 포함:

| 질문 유형 | 도구 | 파라미터 |
|---|---|---|
| 실적산출 대상 | get_regulation_section | subsection="실적산출대상" |
| 평가배점 | get_regulation_section | subsection="평가배점" |
| 득점기준 | get_regulation_section | subsection="평점산출방식" |
| 제외 대상 | get_regulation_section | subsection="실적제외대상" |
| 키워드 검색 | search_best_banker_regulations | query=키워드 |

특이사항: 한글 숫자를 아라비아 숫자로 변환 (1백만원 → 1,000,000원)

---

### BANKER_DASHBOARD_SYSTEM_PROMPT

**목적:** dashboard_agent에게 리포트 형식 지정

핵심 지시:
- 직원번호 출처: `[세션 직원번호]` 메시지 우선 → 이력에서 EMP\d+ 검색 → 사용자에게 질문
- 도구 3개 순서대로 호출: `get_banker_dashboard` → `get_group_statistics` → `get_worst_group`
- 일본어·영어 혼용 금지 (한국어 전용)

---

### RECOMMEND_CLASSIFY_PROMPT

**목적:** classify 노드에서 LLM structured output 분류 기준 제공

분류 기준:
- `A1`: "고객 성향으로", "고객 위주로", "1번", "성향 기반으로"
- `A2`: "부족 상품군으로", "실적 위주로", "2번", "내 약점 상품군으로"
- `null`: 첫 요청이거나 방향 미결정

핵심 설계: 이전 AI가 "고객 성향 중심(1번)? 부족 상품군(2번)?" 형태로 질문했고 사용자가 "1번"/"2번" 응답 → A1/A2 분류. 이 패턴을 명시하여 후속 메시지 처리를 안정화합니다.

---

### RECOMMEND_PATH_A1_PROMPT

**목적:** path_a1 ReAct 에이전트에게 고객 성향 기반 추천 흐름 지시

핵심 지시:
- customer_id 없으면 **도구 호출 없이** 고객번호 요청
- TOP3 상품 출력 후 사용자 선택 대기 (중간 멈춤)
- 선택 후 `generate_marketing_message` 호출

출력 형식:
```
## 추천 TOP3 상품
1. [상품명] ([카테고리]) — 추천점수: N점
...

## 고객 특성
[요약]

원하시는 상품을 알려주시면 마케팅 문구를 생성해드릴게요.
```

---

### RECOMMEND_PATH_A2_PROMPT

**목적:** path_a2 ReAct 에이전트에게 부족 상품군 기반 추천 흐름 지시

핵심 지시:
- `get_top_product_for_customer(category=worst)` 결과가 `{"found": false}`이면:
  - a) "해당 고객에게 [상품군] 추천 이력이 없어 고객 성향 기반 추천으로 전환합니다." 출력
  - b) category 없이 재호출
  - c) 그 결과 사용

출력 형식:
```
## 추천 TOP3 상품 (부족 상품군: [worst_category])
1. [상품명] ([카테고리]) — 추천점수: N점
...
```

---

### SIMULATION_SYSTEM_PROMPT

**목적:** simulation_agent에게 득점 시뮬레이션 형식 지시

핵심 지시:
- 상품명 언급 시 4개 도구 순서대로 반드시 모두 호출
- 사용자가 금액 미언급 시: 득점기준만 안내 후 금액 입력 요청
- 한글 숫자 아라비아 변환 (1백만원 → 1,000,000원)
- 상품 미발견 또는 규정 없으면 솔직하게 안내

출력 구조:
```
## 현재 나의 점수
## [{product_name}] 득점기준
## 시뮬레이션 (금액 언급 시)
## 실적인정기준 (있는 경우만)
```

---

## 4. 에이전트 타입별 설계 원칙

| 에이전트 | 타입 | 최종 출력 생성 주체 | 사용 이유 |
|---|---|---|---|
| customer_agent | ReAct | LLM | 요약 문구는 자연어 생성이 적합 |
| regulation_agent | ReAct | LLM | 규정 해석·인용은 LLM 판단이 필요 |
| dashboard_agent | ReAct | LLM | 수치 분석 + 조언은 LLM이 유연하게 처리 |
| recommendation_agent | StateGraph + ReAct | LLM | 분기 로직은 Python, 추천·마케팅은 LLM |
| **strategy_agent** | **StateGraph (Python)** | **Python 템플릿** | **출력 포맷 강제가 필수** |
| simulation_agent | ReAct | LLM | 수식 계산 + 설명은 LLM이 처리 |

### strategy_agent가 ReAct를 사용하지 않는 이유

RLHF로 훈련된 LLM은 고객 데이터를 받으면 "도움이 되는 전략을 작성해야 한다"는 행동 패턴이 시스템 프롬프트의 금지 지시보다 강하게 작동합니다. 도구 호출 순서가 고정되어 있고 출력 형식도 고정이므로 LLM이 최종 텍스트를 생성할 이유가 없습니다. Python 함수가 직접 `.invoke()`로 도구를 호출하고 문자열 템플릿으로 출력을 조립합니다.

---

## 5. 새 에이전트 추가 체크리스트

1. `app/agents/<name>_agent.py` — `create_<name>_agent(model, checkpointer)` 팩토리 함수
2. `app/agents/prompts.py` — 시스템 프롬프트 추가 (결정론적 타입이면 불필요)
3. `app/agents/banking_agent.py`
   - `AGENTS` Literal에 이름 추가
   - `create_banking_agent()`에 import, 인스턴스 생성, `add_node`, `add_edge` 추가
   - `SUPERVISOR_SYSTEM_PROMPT`에 라우팅 기준 추가
4. `app/services/agent_service.py` — `_BANKING_SUB_AGENTS` set에 이름 추가
5. `banking_ui.html` — `agentLabels` 객체에 `{ label: '...', icon: '...' }` 추가
