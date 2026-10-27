"""KVManager — 진짜: maru_server/kv_manager.py

키 → 위치(어느 영역의 어디부터 몇 바이트)를 적어 두는 장부. 데이터는 건드리지 않고 위치만 기록한다.
도서관 비유 (1.6): KV cache = 책, 영역 = 서가, KVEntry = 도서 목록 한 줄
"""

import enum
from dataclasses import dataclass


@dataclass
class KVEntry:
    """장부 한 줄. 진짜 13~20줄 (pin_count는 지우기 방지용, 운영 구간이라 뺌)"""

    region_id: str  # 어느 영역. 진짜는 int, 호두마루는 OS 이름(str, "psm_…") (1.6)
    kv_offset: int  # 영역 안에서 어디부터 (= page_index × chunk_size, 2.4). 진짜 주석: relative to handle.offset
    kv_length: int  # 몇 바이트 (= AllocHandle.size). 키마다 달라서 핸들이 아니라 장부에 있다 (1.6)


class DeleteResult(enum.Enum):
    """delete 결과. 3장에선 안 씀 (진짜 test_kv_manager.py가 import해서 이름만 정의)"""

    NOT_FOUND = "not_found"
    PINNED = "pinned"
    DELETED = "deleted"


class KVManager:
    def __init__(self):
        # 키 → 장부 한 줄. 진짜와 같음 (진짜의 RLock은 스레드 1개라 뺐다)
        self._store: dict[str, KVEntry] = {}

    def register(
        self, key: str, region_id: str, kv_offset: int, kv_length: int
    ) -> tuple[bool, str | None]:
        """키를 장부에 적는다. 먼저 등록한 쪽이 이긴다 (idempotent: 여러 번 해도 한 번 한 것과 같다)

        - 같은 키 = 같은 앞부분의 KV라 내용이 같다
        - 덮어쓰면: 첫 위치를 읽는 중인 consumer가 있는데 장부에서 사라져 해제 추적이 꼬인다
        - 에러를 던지면: 여러 서버가 같은 프롬프트를 계산하는 흔한 상황을 실패로 만든다

        Returns:
            (is_new, region_id_to_increment)
            - 처음 보는 키: (True, region_id) → 서버가 그 영역의 kv_ref_count를 +1 (진짜 server.py, 6장)
            - 이미 있는 키: (False, None) → 무시
        """
        if key in self._store:
            return (False, None)  # Key already exists — skip
        self._store[key] = KVEntry(region_id=region_id, kv_offset=kv_offset, kv_length=kv_length)
        return (True, region_id)

    def lookup(self, key: str) -> KVEntry | None:
        """키의 위치를 찾는다. 없는 키는 흔한 상황이라 에러 대신 None (2.2 allocate와 같은 이유).

        어떻게 할지는 부르는 쪽(retrieve)이 정한다
        """
        return self._store.get(key)

    def exists(self, key: str) -> bool:
        """키가 장부에 있나. 진짜 test_register_new_key가 이걸로 확인한다 (3.2)"""
        return key in self._store
