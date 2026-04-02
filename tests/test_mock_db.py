import pytest
from fastapi.testclient import TestClient


def test_list_tables(client: TestClient):
    """테이블 목록 반환"""
    response = client.get("/api/v1/mock-db/tables")
    assert response.status_code == 200
    data = response.json()
    assert "tables" in data
    expected = {
        "customer_basic", "customer_profile", "customer_consultation",
        "product_master", "best_banker_status", "best_banker_promotion",
        "product_recommendation",
    }
    assert expected == set(data["tables"])


def test_get_table_data_valid(client: TestClient):
    """customer_basic 페이지네이션 조회"""
    response = client.get("/api/v1/mock-db/tables/customer_basic?page=1&page_size=5")
    assert response.status_code == 200
    data = response.json()
    assert data["table_name"] == "customer_basic"
    assert data["total_count"] > 0
    assert len(data["data"]) <= 5
    assert "customer_id" in data["data"][0]


def test_get_table_data_invalid_table(client: TestClient):
    """존재하지 않는 테이블 → 404 (SQL 오류 아님)"""
    response = client.get("/api/v1/mock-db/tables/nonexistent_table")
    assert response.status_code == 404


def test_get_table_data_sql_injection(client: TestClient):
    """SQL Injection 시도 → 404 (500 아님)"""
    response = client.get("/api/v1/mock-db/tables/customer_basic; DROP TABLE customer_basic--")
    assert response.status_code == 404


def test_get_table_data_pagination(client: TestClient):
    """2페이지 조회 시 올바른 offset 적용"""
    r1 = client.get("/api/v1/mock-db/tables/customer_basic?page=1&page_size=3")
    r2 = client.get("/api/v1/mock-db/tables/customer_basic?page=2&page_size=3")
    assert r1.status_code == 200
    assert r2.status_code == 200
    ids_p1 = [row["customer_id"] for row in r1.json()["data"]]
    ids_p2 = [row["customer_id"] for row in r2.json()["data"]]
    assert ids_p1 != ids_p2


def test_get_record_valid(client: TestClient, db_conn):
    """유효한 레코드 상세 조회"""
    row = db_conn.execute("SELECT customer_id FROM customer_basic LIMIT 1").fetchone()
    assert row is not None, "banking.db에 데이터가 없습니다"
    cid = row["customer_id"]

    response = client.get(f"/api/v1/mock-db/tables/customer_basic/{cid}")
    assert response.status_code == 200
    data = response.json()
    assert data["record"]["customer_id"] == cid


def test_get_record_not_found(client: TestClient):
    """존재하지 않는 ID → 404"""
    response = client.get("/api/v1/mock-db/tables/customer_basic/DOESNOTEXIST")
    assert response.status_code == 404


def test_get_stats(client: TestClient):
    """각 테이블의 count > 0"""
    response = client.get("/api/v1/mock-db/stats")
    assert response.status_code == 200
    stats = response.json()["stats"]
    for table_name, info in stats.items():
        assert info["count"] > 0, f"{table_name} 테이블에 데이터가 없습니다"
