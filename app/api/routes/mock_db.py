import os
import sqlite3
from datetime import datetime

from fastapi import APIRouter, HTTPException

mock_db_router = APIRouter()

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "banking.db")

# 테이블 목록
TABLES = [
    "customer_basic",
    "customer_profile",
    "customer_consultation",
    "product_master",
    "best_banker_status",
    "best_banker_promotion",
    "product_recommendation",
]


def _conn() -> sqlite3.Connection:
    """데이터베이스 연결 객체 생성"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _row_to_dict(row: sqlite3.Row) -> dict:
    """sqlite3.Row를 dict로 변환"""
    return dict(row) if row else None


@mock_db_router.get("/tables")
async def list_tables():
    """모든 테이블 목록 조회"""
    return {
        "tables": TABLES
    }


@mock_db_router.get("/tables/{table_name}")
async def get_table_data(
    table_name: str,
    page: int = 1,
    page_size: int = 20
):
    """테이블 데이터 조회 (페이징)"""
    # 테이블 검증
    if table_name not in TABLES:
        raise HTTPException(status_code=404, detail=f"테이블 '{table_name}'을 찾을 수 없습니다.")

    # page_size 검증
    if page_size > 100:
        page_size = 100
    if page < 1:
        page = 1

    conn = _conn()
    try:
        c = conn.cursor()

        # 전체 행 수
        c.execute(f'SELECT COUNT(*) FROM "{table_name}"')
        total_count = c.fetchone()[0]

        # 페이징 쿼리
        offset = (page - 1) * page_size
        c.execute(
            f'SELECT * FROM "{table_name}" LIMIT ? OFFSET ?',
            (page_size, offset)
        )
        rows = c.fetchall()

        # 전체 페이지 수
        total_pages = (total_count + page_size - 1) // page_size

        return {
            "table_name": table_name,
            "total_count": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "data": [_row_to_dict(row) for row in rows]
        }
    finally:
        conn.close()


@mock_db_router.get("/tables/{table_name}/{id}")
async def get_record(table_name: str, id: str):
    """특정 레코드 상세 조회"""
    # 테이블 검증
    if table_name not in TABLES:
        raise HTTPException(status_code=404, detail=f"테이블 '{table_name}'을 찾을 수 없습니다.")

    conn = _conn()
    try:
        c = conn.cursor()

        # 테이블의 primary key 컬럼 찾기
        c.execute(f'PRAGMA table_info("{table_name}")')
        columns = c.fetchall()
        pk_column = next((col[1] for col in columns if col[5]), None)  # pk 플래그 확인

        if not pk_column:
            # PK를 찾지 못한 경우, 첫 번째 컬럼을 PK로 가정
            pk_column = columns[0][1] if columns else None

        if not pk_column:
            raise HTTPException(status_code=400, detail="테이블 구조를 파악할 수 없습니다.")

        # 레코드 조회 — pk_column도 allowlist(TABLES) 검증된 테이블에서 추출한 값이므로 안전
        c.execute(f'SELECT * FROM "{table_name}" WHERE "{pk_column}" = ?', (id,))
        row = c.fetchone()

        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"테이블 '{table_name}'에서 ID '{id}'를 찾을 수 없습니다."
            )

        return {
            "table_name": table_name,
            "record": _row_to_dict(row)
        }
    finally:
        conn.close()


@mock_db_router.get("/stats")
async def get_stats():
    """테이블별 통계 (행 수, 마지막 업데이트)"""
    conn = _conn()
    try:
        c = conn.cursor()
        stats = {}

        for table_name in TABLES:
            if table_name not in TABLES:  # 방어적 가드 (향후 TABLES 변경 시 대비)
                continue
            # 행 수
            c.execute(f'SELECT COUNT(*) FROM "{table_name}"')
            count = c.fetchone()[0]

            # 마지막 업데이트 시간 (테이블이 생성된 시간으로 대체)
            # SQLite는 메타데이터로 마지막 수정 시간을 직접 제공하지 않으므로,
            # 현재 시각을 반환 (실제 운영 시 TRIGGER로 updated_at 관리)
            updated_at = datetime.utcnow().isoformat()

            stats[table_name] = {
                "count": count,
                "updated_at": updated_at
            }

        return {
            "stats": stats
        }
    finally:
        conn.close()
