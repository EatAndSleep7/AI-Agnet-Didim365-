"""
banking.db 생성 및 가상 데이터 삽입 스크립트
실행: uv run python app/data/create_mock_data.py

상품코드 체계 (8자리, 중복 없음):
  CC PP SSSS
  CC   = 카테고리 (01=수신, 02=개인여신, 03=기업여신, 04=디지털금융)
  PP   = 부분류   (01~07)
  SSSS = 순번     (0001~9999)
"""
import sqlite3
import random
import os
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "banking.db")

# ── 상품 원장 (규정집 실적산출대상 기준) ─────────────────────────────────────────
# (product_id, category, sub_category, product_name, regulation_code)
# product_id  : 8자리 통일 코드 (CC PP SSSS)
# regulation_code : 규정집 원본 코드 (없으면 None)
PRODUCT_MASTER = [
    # ── 수신 (01) ─────────────────────────────────────────────────────────────
    # 핵심예금 (0101)
    ("01010001", "수신", "핵심예금",    "보통예금",               "01"),
    ("01010002", "수신", "핵심예금",    "저축예금",               "02"),
    ("01010003", "수신", "핵심예금",    "당좌예금",               "05"),
    ("01010004", "수신", "핵심예금",    "가계당좌예금",           "06"),
    ("01010005", "수신", "핵심예금",    "자유저축예금",           "12"),
    ("01010006", "수신", "핵심예금",    "기업자유예금",           "17"),
    # MMDA (0102)
    ("01020001", "수신", "MMDA",        "알짜배기저축예금",       "12"),
    ("01020002", "수신", "MMDA",        "알짜배기기업예금",       "17"),
    # 적립식 (0103)
    ("01030001", "수신", "적립식",      "정기적금",               "04"),
    ("01030002", "수신", "적립식",      "평생우대적금",           "34"),
    ("01030003", "수신", "적립식",      "자유로우대적금",         "47"),
    ("01030004", "수신", "적립식",      "상호부금",               "59"),
    # 거치식 (0104)
    ("01040001", "수신", "거치식",      "정기예금",               "03"),
    ("01040002", "수신", "거치식",      "(신)자유적립정기예금",   "23"),
    ("01040003", "수신", "거치식",      "환매채",                 "25"),
    ("01040004", "수신", "거치식",      "자유로 정기예금",        "33"),
    ("01040005", "수신", "거치식",      "표지어음",               "48"),
    ("01040006", "수신", "거치식",      "농금채",                 "58"),
    ("01040007", "수신", "거치식",      "양도성예금증서",         "76"),
    # 주거래계좌 (0105)
    ("01050001", "수신", "주거래계좌",  "급여·가맹점·의료비계좌", None),
    ("01050002", "수신", "주거래계좌",  "카드결제계좌",            None),

    # ── 개인여신 (02) ─────────────────────────────────────────────────────────
    # 전세자금 (0201)
    ("02010001", "개인여신", "전세자금",       "NH전세대출",          "1168,1616,1723,1740,2019,2051,3886"),
    ("02010002", "개인여신", "전세자금",       "NH모바일전세대출",    "2037"),
    ("02010003", "개인여신", "전세자금",       "NH청년전월세",        "3595,3596"),
    ("02010004", "개인여신", "전세자금",       "NH모바일전세대출+",   "3942,3943,3944,3945,4259,4260,4261"),
    # 우량신용 (0202)
    ("02020001", "개인여신", "우량신용",       "신나는직장인대출",    "1529,625,1530,626,777,1162,624"),
    ("02020002", "개인여신", "우량신용",       "NH튼튼직장인대출",   "2653"),
    ("02020003", "개인여신", "우량신용",       "공무원협약대출",      "80,82,83,84,85,86,87,304,471,684"),
    ("02020004", "개인여신", "우량신용",       "NH금융리더론",        "1870,1871"),
    ("02020005", "개인여신", "우량신용",       "NH직장인대출V",       "2120"),
    ("02020006", "개인여신", "우량신용",       "NH메디프로론",        "1394,1448,1449"),
    ("02020007", "개인여신", "우량신용",       "슈퍼프로론",          "1097,1098,1099,1100,1101,1102,1624"),
    # 서민금융 (0203)
    ("02030001", "개인여신", "서민금융",       "NH새희망홀씨",        "1807,1820,2094,4058"),
    # 주택담보 (0204)
    ("02040001", "개인여신", "주택담보",       "주택담보대출",        None),
    # 기타담보 (0205)
    ("02050001", "개인여신", "기타담보",       "기타담보대출",        None),
    # 기타가계여신 (0206)
    ("02060001", "개인여신", "기타가계여신",   "기타가계여신",        None),
    # 비대면신용여신 (0207)
    ("02070001", "개인여신", "비대면신용여신", "비대면신용대출",      None),

    # ── 기업여신 (03) ─────────────────────────────────────────────────────────
    # 일반자금 (0301) — 운전자금
    ("03010001", "기업여신", "일반자금", "농식품기업운전자금대출",     "1211111111100"),
    ("03010002", "기업여신", "일반자금", "구매자금대출",               "1211111111500"),
    ("03010003", "기업여신", "일반자금", "농식품기업당좌대출",         "1211111111700"),
    ("03010004", "기업여신", "일반자금", "할인어음",                   "1211111112100"),
    ("03010005", "기업여신", "일반자금", "당좌대출",                   "1211111112300"),
    ("03010006", "기업여신", "일반자금", "일반운전자금대출금",         "1211111112500"),
    ("03010007", "기업여신", "일반자금", "외상매출채권담보대출",       "1211111112700"),
    ("03010008", "기업여신", "일반자금", "적금관계대출",               "1211111112900"),
    ("03010009", "기업여신", "일반자금", "무역금융",                   "1211111113100"),
    ("03010010", "기업여신", "일반자금", "주택자금대출(운전)",         "1211111113300"),
    # 일반자금 (0301) — 시설자금
    ("03010011", "기업여신", "일반자금", "농식품기업시설자금대출",     "1211113111300"),
    ("03010012", "기업여신", "일반자금", "일반시설자금대출",           "1211113111700"),
    ("03010013", "기업여신", "일반자금", "주택자금대출(시설)",         "1211113111900"),
    # 정책자금 (0302)
    ("03020001", "기업여신", "정책자금", "재정농업중기대출",           "1211113131312"),
    ("03020002", "기업여신", "정책자금", "기타재정시설대출",           "1211113139912"),
    ("03020003", "기업여신", "정책자금", "기타재정운전자금대출",       "1211111139911"),

    # ── 디지털금융 (04) ───────────────────────────────────────────────────────
    # 개인디지털금융 (0401)
    ("04010001", "디지털금융", "개인디지털금융", "NH올원뱅크",        None),
    ("04010002", "디지털금융", "개인디지털금융", "NH모바일인증서",    None),
    ("04010003", "디지털금융", "개인디지털금융", "NH손하나로 인증",   None),
    ("04010004", "디지털금융", "개인디지털금융", "NH마이데이터",      None),
    ("04010005", "디지털금융", "개인디지털금융", "오픈뱅킹",          None),
    ("04010006", "디지털금융", "개인디지털금융", "NH멤버스",          None),
    # 기업디지털금융 (0402)
    ("04020001", "디지털금융", "기업디지털금융", "펌뱅킹(HOST)",     None),
    ("04020002", "디지털금융", "기업디지털금융", "가상계좌",          None),
    ("04020003", "디지털금융", "기업디지털금융", "하나로브랜치",      None),
    ("04020004", "디지털금융", "기업디지털금융", "금결원CMS",         None),
    ("04020005", "디지털금융", "기업디지털금융", "하나로sERP",        None),
    ("04020006", "디지털금융", "기업디지털금융", "NH기업스마트뱅킹",  None),
]

CATEGORIES = ["수신", "개인여신", "기업여신", "디지털금융"]

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
        customer_id                TEXT PRIMARY KEY,
        customer_name              TEXT NOT NULL,
        deposit_balance            REAL DEFAULT 0,
        loan_balance               REAL DEFAULT 0,
        is_mobile_banking_active   INTEGER DEFAULT 0,
        is_open_banking_joined     INTEGER DEFAULT 0,
        is_mydata_joined           INTEGER DEFAULT 0,
        has_salary_transfer        INTEGER DEFAULT 0,
        has_utility_auto_transfer  INTEGER DEFAULT 0,
        is_marketing_agreed        INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS customer_profile (
        customer_id               TEXT PRIMARY KEY,
        is_married_estimated      INTEGER DEFAULT 0,
        has_car_estimated         INTEGER DEFAULT 0,
        has_children_estimated    INTEGER DEFAULT 0,
        is_homeowner_estimated    INTEGER DEFAULT 0,
        avg_weekend_spend_count   INTEGER DEFAULT 0,
        avg_night_spend_count     INTEGER DEFAULT 0,
        last_contact_elapsed_days INTEGER DEFAULT 0,
        FOREIGN KEY (customer_id) REFERENCES customer_basic (customer_id)
    );

    CREATE TABLE IF NOT EXISTS customer_consultation (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id        TEXT NOT NULL,
        product_id         TEXT,
        product_name       TEXT,
        interaction_result INTEGER DEFAULT 0,
        consulted_at       TEXT,
        FOREIGN KEY (customer_id) REFERENCES customer_basic (customer_id),
        FOREIGN KEY (product_id)  REFERENCES product_master (product_id)
    );

    CREATE TABLE IF NOT EXISTS product_master (
        product_id       TEXT PRIMARY KEY,
        category         TEXT NOT NULL,
        sub_category     TEXT NOT NULL,
        product_name     TEXT NOT NULL,
        regulation_code  TEXT,
        is_active        INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS best_banker_status (
        employee_id          TEXT PRIMARY KEY,
        deposit_score        REAL DEFAULT 0.0,
        personal_loan_score  REAL DEFAULT 0.0,
        corporate_loan_score REAL DEFAULT 0.0,
        digital_score        REAL DEFAULT 0.0,
        total_score          REAL DEFAULT 0.0,
        last_updated         TEXT
    );

    CREATE TABLE IF NOT EXISTS best_banker_promotion (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id    TEXT NOT NULL,
        customer_id    TEXT NOT NULL,
        category       TEXT NOT NULL,
        product_id     TEXT NOT NULL,
        promotion_date TEXT DEFAULT (DATETIME('now', 'localtime')),
        FOREIGN KEY (employee_id) REFERENCES best_banker_status (employee_id),
        FOREIGN KEY (customer_id) REFERENCES customer_basic (customer_id),
        FOREIGN KEY (product_id)  REFERENCES product_master (product_id)
    );

    CREATE TABLE IF NOT EXISTS product_recommendation (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id     TEXT,
        category        TEXT,
        product_id      TEXT,
        recommend_score INTEGER,
        FOREIGN KEY (customer_id) REFERENCES customer_basic (customer_id),
        FOREIGN KEY (product_id)  REFERENCES product_master (product_id)
    );
    """)


def insert_product_master(cur):
    cur.executemany(
        "INSERT OR IGNORE INTO product_master "
        "(product_id, category, sub_category, product_name, regulation_code) "
        "VALUES (?,?,?,?,?)",
        PRODUCT_MASTER,
    )
    print(f"  product_master: {len(PRODUCT_MASTER)}건")


def insert_customers(cur, n=50):
    basics, profiles, consultations = [], [], []

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
        for _ in range(random.randint(2, 4)):
            pid, _, _, pname, _ = random.choice(PRODUCT_MASTER)
            consultations.append((
                cid, pid, pname,
                random.choice([-1, 0, 0, 1, 1]),
                random_date(),
            ))

    cur.executemany("INSERT OR IGNORE INTO customer_basic VALUES (?,?,?,?,?,?,?,?,?,?)", basics)
    cur.executemany("INSERT OR IGNORE INTO customer_profile VALUES (?,?,?,?,?,?,?,?)", profiles)
    cur.executemany(
        "INSERT INTO customer_consultation "
        "(customer_id, product_id, product_name, interaction_result, consulted_at) "
        "VALUES (?,?,?,?,?)",
        consultations,
    )
    print(f"  customer_basic: {len(basics)}건")
    print(f"  customer_profile: {len(profiles)}건")
    print(f"  customer_consultation: {len(consultations)}건")


def insert_bankers(cur, n=20):
    rows = []
    for i in range(1, n + 1):
        eid   = f"EMP{i:03d}"
        dep   = round(random.uniform(50, 250), 1)
        p_lon = round(random.uniform(30, 200), 1)
        c_lon = round(random.uniform(30, 200), 1)
        dig   = round(random.uniform(20, 100), 1)
        total = round(dep + p_lon + c_lon + dig, 1)
        rows.append((eid, dep, p_lon, c_lon, dig, total, random_date(30, 1)))
    cur.executemany("INSERT OR IGNORE INTO best_banker_status VALUES (?,?,?,?,?,?,?)", rows)
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
        pid, category, _, _, _ = random.choice(PRODUCT_MASTER)
        rows.append((eid, cid, category, pid, random_date(90, 1)))

    cur.executemany(
        "INSERT INTO best_banker_promotion "
        "(employee_id, customer_id, category, product_id, promotion_date) "
        "VALUES (?,?,?,?,?)",
        rows,
    )
    print(f"  best_banker_promotion: {len(rows)}건")


def insert_recommendations(cur):
    cur.execute("SELECT customer_id FROM customer_basic")
    cids = [r[0] for r in cur.fetchall()]

    by_category: dict[str, list] = {c: [] for c in CATEGORIES}
    for row in PRODUCT_MASTER:
        by_category[row[1]].append(row)

    rows = []
    for cid in cids:
        for category, products in by_category.items():
            sampled = random.sample(products, random.randint(2, min(5, len(products))))
            for row in sampled:
                pid, cat, _, _, _ = row
                rows.append((cid, cat, pid, random.randint(1, 1000)))

    cur.executemany(
        "INSERT INTO product_recommendation (customer_id, category, product_id, recommend_score) "
        "VALUES (?,?,?,?)",
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
    insert_product_master(cur)
    insert_customers(cur)
    insert_bankers(cur)
    insert_promotions(cur)
    insert_recommendations(cur)

    conn.commit()
    conn.close()
    print(f"\n완료: {DB_PATH}")


if __name__ == "__main__":
    main()
