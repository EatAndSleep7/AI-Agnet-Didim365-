"""
banking.db 생성 및 가상 데이터 삽입 스크립트
실행: uv run python app/data/create_mock_data.py
"""
import sqlite3
import random
import os
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "banking.db")

# ── 상품 정의 ──────────────────────────────────────────────────────────────────
PRODUCTS = {
    1: [  # 수신
        ("DEP101", "정기예금 플러스", 12.5),
        ("DEP102", "자유적금", 8.0),
        ("DEP103", "청년우대적금", 15.0),
        ("DEP104", "프리미엄 IRP", 20.0),
        ("DEP105", "퇴직연금 DC형", 18.0),
    ],
    2: [  # 여신
        ("LON201", "신용대출 스탠다드", 10.0),
        ("LON202", "주택담보대출", 25.0),
        ("LON203", "전세자금대출", 20.0),
        ("LON204", "소상공인대출", 15.0),
        ("LON205", "자동차할부대출", 8.0),
    ],
    3: [  # 전자금융
        ("DIG301", "모바일뱅킹 가입", 5.0),
        ("DIG302", "오픈뱅킹 연결", 5.0),
        ("DIG303", "마이데이터 연동", 7.0),
        ("DIG304", "급여이체 등록", 10.0),
        ("DIG305", "공과금 자동이체", 8.0),
    ],
}

GROUP_NAMES = {1: "수신(예적금)", 2: "여신(대출)", 3: "전자금융"}

KOREAN_SURNAMES = ["김", "이", "박", "최", "정", "강", "조", "윤", "장", "임"]
KOREAN_NAMES = ["민준", "서연", "지호", "수아", "도현", "지민", "예준", "채원", "시우", "지우",
                "준서", "서현", "주원", "하은", "승현", "유나", "현우", "지아", "태양", "수빈"]


def random_name():
    return random.choice(KOREAN_SURNAMES) + random.choice(KOREAN_NAMES)


def random_date(start_days_ago=365, end_days_ago=1):
    delta = random.randint(end_days_ago, start_days_ago)
    dt = datetime.now() - timedelta(days=delta)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def create_schema(cur):
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS customer_basic (
        customer_id TEXT PRIMARY KEY,
        customer_name TEXT NOT NULL,
        deposit_balance REAL DEFAULT 0,
        loan_balance REAL DEFAULT 0,
        is_mobile_banking_active INTEGER DEFAULT 0,
        is_open_banking_joined INTEGER DEFAULT 0,
        is_mydata_joined INTEGER DEFAULT 0,
        has_salary_transfer INTEGER DEFAULT 0,
        has_utility_auto_transfer INTEGER DEFAULT 0,
        is_marketing_agreed INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS customer_profile (
        customer_id TEXT PRIMARY KEY,
        is_married_estimated INTEGER DEFAULT 0,
        has_car_estimated INTEGER DEFAULT 0,
        has_children_estimated INTEGER DEFAULT 0,
        is_homeowner_estimated INTEGER DEFAULT 0,
        avg_weekend_spend_count INTEGER DEFAULT 0,
        avg_night_spend_count INTEGER DEFAULT 0,
        last_contact_elapsed_days INTEGER DEFAULT 0,
        FOREIGN KEY (customer_id) REFERENCES customer_basic (customer_id)
    );

    CREATE TABLE IF NOT EXISTS customer_consultation (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id TEXT NOT NULL,
        product_code TEXT,
        product_name TEXT,
        interaction_result INTEGER DEFAULT 0,
        consulted_at TEXT,
        FOREIGN KEY (customer_id) REFERENCES customer_basic (customer_id)
    );

    CREATE TABLE IF NOT EXISTS best_banker_status (
        employee_id TEXT PRIMARY KEY,
        deposit_score REAL DEFAULT 0.0,
        loan_score REAL DEFAULT 0.0,
        digital_score REAL DEFAULT 0.0,
        total_score REAL DEFAULT 0.0,
        last_updated TEXT
    );

    CREATE TABLE IF NOT EXISTS banker_score_config (
        product_code TEXT PRIMARY KEY,
        product_group_code INTEGER,
        product_name TEXT,
        add_score REAL DEFAULT 0.0
    );

    CREATE TABLE IF NOT EXISTS best_banker_promotion (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id TEXT NOT NULL,
        customer_id TEXT NOT NULL,
        product_group_code INTEGER NOT NULL,
        product_code TEXT NOT NULL,
        promotion_date TEXT DEFAULT (DATETIME('now', 'localtime')),
        FOREIGN KEY (employee_id) REFERENCES best_banker_status (employee_id),
        FOREIGN KEY (customer_id) REFERENCES customer_basic (customer_id)
    );

    CREATE TABLE IF NOT EXISTS product_recommendation (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id TEXT,
        product_group_code INTEGER,
        product_code TEXT,
        recommend_score INTEGER,
        FOREIGN KEY (customer_id) REFERENCES customer_basic (customer_id)
    );
    """)


def insert_banker_score_config(cur):
    rows = []
    for group_code, products in PRODUCTS.items():
        for product_code, product_name, add_score in products:
            rows.append((product_code, group_code, product_name, add_score))
    cur.executemany(
        "INSERT OR IGNORE INTO banker_score_config VALUES (?,?,?,?)", rows
    )
    print(f"  banker_score_config: {len(rows)}건")


def insert_customers(cur, n=50):
    basics, profiles, consultations = [], [], []
    all_products = [(pc, pn, gc) for gc, prods in PRODUCTS.items() for pc, pn, _ in prods]

    for i in range(1, n + 1):
        cid = f"CUST{i:03d}"
        basics.append((
            cid,
            random_name(),
            round(random.uniform(100_000, 50_000_000), 0),
            round(random.uniform(0, 30_000_000), 0),
            random.randint(0, 1),
            random.randint(0, 1),
            random.randint(0, 1),
            random.randint(0, 1),
            random.randint(0, 1),
            random.randint(0, 1),
        ))
        profiles.append((
            cid,
            random.randint(0, 1),
            random.randint(0, 1),
            random.randint(0, 1),
            random.randint(0, 1),
            random.randint(0, 15),
            random.randint(0, 8),
            random.randint(0, 180),
        ))
        # 상담 이력: 고객당 2~4건
        for _ in range(random.randint(2, 4)):
            pc, pn, _ = random.choice(all_products)
            consultations.append((
                cid, pc, pn,
                random.choice([-1, 0, 0, 1, 1]),
                random_date(),
            ))

    cur.executemany("INSERT OR IGNORE INTO customer_basic VALUES (?,?,?,?,?,?,?,?,?,?)", basics)
    cur.executemany("INSERT OR IGNORE INTO customer_profile VALUES (?,?,?,?,?,?,?,?)", profiles)
    cur.executemany(
        "INSERT INTO customer_consultation (customer_id, product_code, product_name, interaction_result, consulted_at) VALUES (?,?,?,?,?)",
        consultations,
    )
    print(f"  customer_basic: {len(basics)}건")
    print(f"  customer_profile: {len(profiles)}건")
    print(f"  customer_consultation: {len(consultations)}건")


def insert_bankers(cur, n=20):
    rows = []
    for i in range(1, n + 1):
        eid = f"EMP{i:03d}"
        dep = round(random.uniform(50, 250), 1)
        lon = round(random.uniform(50, 250), 1)
        dig = round(random.uniform(20, 100), 1)
        total = round(dep + lon + dig, 1)
        rows.append((eid, dep, lon, dig, total, random_date(30, 1)))
    cur.executemany("INSERT OR IGNORE INTO best_banker_status VALUES (?,?,?,?,?,?)", rows)
    print(f"  best_banker_status: {len(rows)}건")


def insert_promotions(cur, n=80):
    cur.execute("SELECT customer_id FROM customer_basic")
    cids = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT employee_id FROM best_banker_status")
    eids = [r[0] for r in cur.fetchall()]

    rows = []
    for _ in range(n):
        eid = random.choice(eids)
        cid = random.choice(cids)
        gc = random.choice([1, 2, 3])
        pc, _, _ = random.choice(PRODUCTS[gc])
        rows.append((eid, cid, gc, pc, random_date(90, 1)))

    cur.executemany(
        "INSERT INTO best_banker_promotion (employee_id, customer_id, product_group_code, product_code, promotion_date) VALUES (?,?,?,?,?)",
        rows,
    )
    print(f"  best_banker_promotion: {len(rows)}건")


def insert_recommendations(cur):
    cur.execute("SELECT customer_id FROM customer_basic")
    cids = [r[0] for r in cur.fetchall()]

    rows = []
    for cid in cids:
        for group_code, products in PRODUCTS.items():
            # 상품군 내 일부 상품(2~5개)에 추천 점수 부여
            sampled = random.sample(products, random.randint(2, len(products)))
            for pc, _, _ in sampled:
                rows.append((cid, group_code, pc, random.randint(1, 1000)))

    cur.executemany(
        "INSERT INTO product_recommendation (customer_id, product_group_code, product_code, recommend_score) VALUES (?,?,?,?)",
        rows,
    )
    print(f"  product_recommendation: {len(rows)}건")


def main():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"기존 DB 삭제: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()

    print("스키마 생성 중...")
    create_schema(cur)

    print("데이터 삽입 중...")
    insert_banker_score_config(cur)
    insert_customers(cur)
    insert_bankers(cur)
    insert_promotions(cur)
    insert_recommendations(cur)

    conn.commit()
    conn.close()
    print(f"\n완료: {DB_PATH}")


if __name__ == "__main__":
    main()
