import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from elasticsearch import Elasticsearch
from app.core.config import settings

es_cfg = settings.ES
print(f"🔗 Elasticsearch 연결 시도...")
print(f"   URL: {es_cfg.URL}")
print(f"   User: {es_cfg.USER}")
print(f"   Index: {es_cfg.INDEX}")

try:
    es = Elasticsearch(
        es_cfg.URL,
        basic_auth=(es_cfg.USER, es_cfg.PASSWORD),
        verify_certs=False,
    )
    info = es.info()
    print(f"✅ 연결 성공!")
    print(f"   Version: {info['version']['number']}")

    # 인덱스 확인
    indices = es.indices.get(index=es_cfg.INDEX)
    print(f"✅ 인덱스 '{es_cfg.INDEX}' 존재: {es_cfg.INDEX in indices}")

    # 문서 개수 확인
    count = es.count(index=es_cfg.INDEX)
    print(f"   문서 수: {count['count']}")

    # 간단한 검색 테스트
    result = es.search(index=es_cfg.INDEX, query={"match_all": {}}, size=1)
    print(f"✅ 검색 테스트 성공 (총 {result['hits']['total']['value']}개 문서)")

except Exception as e:
    print(f"❌ 연결 실패!")
    print(f"   오류: {e}")
    import traceback
    traceback.print_exc()
