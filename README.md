# hodu-maru

진짜 [Maru](https://github.com/xcena-dev/maru)를 따라 만드는 학습용 미니 Maru.
이름·구조는 진짜 Maru를 따르고, 목표물은 진짜 Maru 코드(예제·단위 테스트)다. import만 `maru` → `hodu_maru`로 바꿔서 통과시킨다.

## 목표

Maru 예제 `examples/producer.py` + `consumer.py`를 코드 한 줄도 안 고치고(import만 변경) 호두마루 위에서 돌린다.
터미널 3개: 서버 / producer / consumer.

- producer: `alloc` → buf에 직접 쓰기 → `store`
- consumer: `retrieve`로 producer의 영역을 복사 없이 읽기
- **끝났다는 증거:** consumer가 1MB 청크 3개를 정확히 읽고, 소켓으로 오간 바이트는 수백 바이트 수준임을 직접 재서 출력 → *"Metadata traveled, data didn't."*

## 실행

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/unit -v
```

## 로드맵 (핵심 구간: 1~5장)

장 = Maru 부품 하나(장 이름도 진짜 부품 이름), 스텝 = 1.1, 1.2 …
장이 끝나면 그 장의 실험·코드·결과로 **문제**를 풀고 다음 장으로 넘어간다.

### 1장 Region — 내 영역 만들고, 남의 영역에 붙기 ✔
진짜: `maru_shm/`(MaruShmClient, MaruHandle), `maru_handler/memory/mapper.py`

- [x] 1.1 공유 메모리 도구 불러오기
- [x] 1.2 owned region 만들기 + 크기 확인 (OS 페이지 16KB 올림)
- [x] 1.3 shared region으로 붙기 (같은 물리 메모리, zero-copy)
- [x] 1.4 숫자 이름으로 붙기 → TypeError
- [x] 1.5 close / unlink (진짜 해제 = 이름 없음 + 창 0개)
- [x] 1.6 호두마루 `MaruHandle(region_id, offset, length)` 정하기
- [x] 1.7 `shm.py`: `MaruShmClient` (alloc / free / mmap / munmap)
- [x] 1.8 `handler.py`: `connect()` / `close()`
- [ ] 1.9 (선택) 손님 창을 `track=True`로 붙여 버그 재현
- ✔ producer 에러가 `alloc`(2장)으로 넘어감
- [x] 1장 문제 (1차 30문항, 2차 틀린 것 20문항)

### 2장 PagedMemoryAllocator — 영역을 마루 Page로 나눠 빌려주기 ✔
진짜: `maru_handler/memory/allocator.py`

- [x] 2.1 예측: 100MB 영역에 1MB 페이지면 몇 개? 남는 바이트는? → 100개, 0바이트, 자투리는 `//`로 버림
- [x] 2.2 `allocator.py`: `allocate() -> int | None`, `free(i)`, deque free list
- [x] 2.3 진짜 `tests/unit/test_allocator.py`(13개) import만 바꿔 통과
- [x] 2.3b 깨보기: `popleft` → `pop` → `test_allocate_single` 1개만 깨짐
- [x] 2.4 `handler.alloc(size)`: page_index → offset = page_index × chunk_size → `AllocHandle`
- ✔ test_allocator 13개 통과 + producer 에러가 `store`(3장)로 넘어감
- [x] 2장 문제 (1차 14문항, 2차 틀린 것 8문항 객관식)

### 3장 KVManager · MaruServer — 키 → 위치 장부 ← 다음
진짜: `maru_server/kv_manager.py`, `rpc_server.py`, `maru_common/serializer.py`

- [ ] 3.1 `KVManager`, `KVEntry(region_id, kv_offset, kv_length)`: `register`(먼저 등록한 쪽이 이김), `lookup`
- [ ] 3.2 진짜 `test_kv_manager.py`의 register/lookup 쪽 통과
- [ ] 3.3 `server.py`: ZMQ REP + msgpack, `python -m hodu_maru.server`
- [ ] 3.4 `rpc_client.py`: register / lookup 요청
- [ ] 3.5 `handler.store()`
- ✔ producer가 "All keys stored"까지 가고, consumer 에러가 `retrieve`(4장)로 넘어감
- [ ] 3장 문제

### 4장 retrieve — 위치를 묻고 남의 영역을 복사 없이 읽기
진짜: `maru_handler/handler.py`

- [ ] 4.1 `handler.retrieve()`: lookup → 내 영역이면 바로, 남의 영역이면 붙고(캐시) → 슬라이스
- [ ] 4.2 터미널 3개로 예제 통과
- [ ] 4.3 소켓 바이트 측정 → "Metadata traveled, data didn't."를 숫자로
- [ ] 4.4 shared region 쓰기를 진짜 마루는 어떻게 다루나
- ✔ **목표 달성**
- [ ] 4장 문제

### 5장 쓰기 순서 — 왜 "쓰기 먼저, 등록 나중"인가
진짜: Architecture Overview의 Store 흐름, Consistency and Safety §1

- [ ] 5.1 "등록 먼저, 쓰기 나중" + sleep → consumer가 반쯤 쓰인 데이터를 읽는 걸 재현
- [ ] 5.2 (선택) 이름으로 붙은 다른 프로세스가 KV를 덮어쓰기 → auth_token이 없으면 생기는 오염 재현
- ✔ 재현되고, 원래 순서로 돌리면 사라짐
- [ ] 5장 문제

## Maru 3계층 ↔ hodu-maru

| 계층 | 진짜 Maru | hodu-maru |
|---|---|---|
| Memory | Pool → Region → Page, Resource Manager(C++)가 영역 발급 | Region = `multiprocessing.shared_memory` 1개 |
| Client | `MaruHandler`, `MaruShmClient`, `PagedMemoryAllocator` | `handler.py`(connect/close/alloc), `shm.py` ✔, `allocator.py` ✔ |
| Metadata | `MaruServer` → `KVManager` | `server.py`: dict + ZMQ + msgpack (3장) |
