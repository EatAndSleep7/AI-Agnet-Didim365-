# 🩺 Medical AI Agent (LangChain & FastAPI)

FastAPI 기반의 **LangChain v1.0 및 LangGraph**를 활용하여 구축된, 건강 및 의료 정보 제공용 특화 AI 에이전트 템플릿입니다. 사용자의 질문 의도를 파악하고 적절한 도구(외부 API 및 검색엔진)를 활용하여 정확하고 안전한 의료 정보를 제공합니다.

---

## 🚀 주요 기능 (Features)

1. **증상 기반 의료 정보 검색 (`search_symptoms`)**
   - Elasticsearch(BM25)를 사용하여 구축된 지식 베이스(`edu-collection`)에서 관련 질환 및 증상 정보를 검색합니다.
2. **약물 정보 조회 (`get_medication_info`)**
   - 식품의약품안전처(e약은요) 공공 API를 연동하여 약물의 효능, 사용법, 주의사항, 부작용 및 보관법 등을 실시간으로 제공합니다.
3. **주변 병원 검색 (`find_nearby_hospitals`)**
   - 건강보험심사평가원 병원정보서비스 API를 활용하여, 사용자가 위치한 지역과 원하는 진료 과목/종별에 맞는 병원 목록을 조회합니다.
4. **안전성 및 도메인 준수 (Safe & Focused)**
   - 의료와 무관한 질문(예: IT 기기 추천, 날씨 등)에 대해서는 정중히 답변을 거절하도록 프롬프트가 구성되어 있습니다.
   - 의료 정보 제공 시, 반드시 "전문의와 상담하거나 병원을 방문하라"는 **면책 조항(Disclaimer)**을 포함하도록 설계되었습니다.
5. **대화 문맥 유지 (Memory & Checkpointing)**
   - LangGraph의 `AsyncSqliteSaver`를 사용하여 대화 내역(`checkpoints.db`)을 저장하고, `thread_id`를 기반으로 이전 대화의 문맥을 이어나갑니다.

---

## 🛠 기술 스택 (Tech Stack)

* **Backend Framework**: `FastAPI`, `Uvicorn`
* **LLM & Orchestration**: `LangChain v1.0`, `LangGraph`, `OpenAI (GPT-4o)`
* **Data Retrieval**: `Elasticsearch` (`langchain-elasticsearch`)
* **Evaluation & Observability**: `Opik`
* **Package Manager**: `uv`

---

## 📂 프로젝트 구조 (Project Structure)

```text
agent/
├── app/
│   ├── agents/                   # LLM 에이전트 핵심 로직
│   │   ├── medical_agent.py      # 에이전트 생성 (create_medical_agent)
│   │   ├── tools.py              # 외부 연동 Tool (증상 검색, 일반약/병원 정보 API)
│   │   └── prompts.py            # 시스템 프롬프트 (의료 도메인 특화 및 안전 가이드)
│   ├── api/                      # FastAPI 라우터 및 엔드포인트
│   ├── core/                     # 앱 설정 (Config, 환경변수)
│   ├── models/                   # Pydantic 데이터 모델
│   ├── services/                 # 비즈니스 로직 
│   │   └── agent_service.py      # 비동기 LLM 스트리밍 및 체크포인트 관리
│   └── main.py                   # FastAPI 애플리케이션 진입점
├── checkpoints.db                # SQLite 기반 대화 이력 저장소
├── evaluate_agent.py             # Opik을 활용한 LLM 자동 평가 스크립트
├── env.sample                    # 환경변수 템플릿 파일
├── pyproject.toml                # 프로젝트 의존성 관리 (uv / hatchling)
└── README.md
```

---

## ⚙️ 실행 및 설치 가이드

### 1. 사전 요구사항 (Prerequisites)
* **Python 3.11 \~ 3.13** 권장
* **`uv` 패키지 매니저** 설치:
  ```bash
  # macOS / Linux / Windows (WSL)
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

### 2. 의존성 설치
프로젝트 루트 폴더에서 아래 명령어를 실행하여 가상환경(`.venv`)을 생성하고 필요한 패키지들을 셋업합니다.
```bash
uv sync
```

### 3. 환경 변수 설정
`env.sample`을 복사하여 `.env` 파일을 생성한 뒤, 필요한 API Key들을 입력합니다.
```bash
cp env.sample .env
```
`.env` 파일 설정 예시:
```env
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4o

# Opik Observability (선택)
OPIK_API_KEY=your_opik_api_key
OPIK_WORKSPACE=your_workspace_name
OPIK_PROJECT=your_project_name
```

### 4. 개발 서버 실행
환경 설정이 모두 완료되면 FastAPI 서버를 실행합니다.
```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
* **API 문서 (Swagger UI)**: 브라우저에서 `http://localhost:8000/docs` 로 접속하여 API 명세를 확인하고 테스트할 수 있습니다.

---

## 🧪 에이전트 평가 (Agent Evaluation with Opik)

의료 특화 AI 모델의 안전성과 정확성을 보장하기 위해, `Opik` 프레임워크를 기반으로 자동 평가 스크립트(`evaluate_agent.py`)를 제공합니다. 평가는 다음과 같은 `Metric`을 바탕으로 진행됩니다.

1. **AnswerRelevance (답변 적절성)**: 사용자의 질문에 직접적이고 명확하게 답변했는가?
2. **Hallucination (환각)**: 제공된 맥락(검색된 문서)을 넘어서 허위 사실을 지어내지 않았는가?
3. **Moderation (유해성)**: 유해하거나 위험한 컨텐츠가 포함되었는가?
4. **DomainAdherence (도메인 준수력, G-Eval)**: 의료 정보 범위를 벗어난 질문(날씨, 코딩, 주식, 여행 등)을 올바르게 거절하는가?
5. **MedicalDisclaimer (면책 조항, G-Eval)**: 의학적 질문에 진단을 확언하지 않고, 병원 방문이나 전문의 상담을 권고하는가?

### 평가 실행 방법
```bash
uv run python evaluate_agent.py
```
평가가 끝나면 `Opik` 대시보드에서 각 질문(10개의 도메인 밖 질문 포함 약 40개의 샘플)별 상세 점수와 통계를 확인할 수 있습니다.
