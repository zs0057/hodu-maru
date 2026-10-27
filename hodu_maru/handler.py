"""MaruHandler — 진짜: maru_handler/handler.py (약 1500줄 → 여기선 수십 줄이 목표)

예제가 부르는 것: MaruHandler(config), with 문, alloc(size), store(key, handle), retrieve(key).
몸통은 장마다 같이 채운다. NotImplementedError 메시지가 "다음에 만들 것"이다.
"""

import logging

from hodu_maru.allocator import PagedMemoryAllocator
from hodu_maru.config import MaruConfig
from hodu_maru.rpc_client import RpcClient
from hodu_maru.shm import MaruShmClient
from hodu_maru.types import AllocHandle, MaruHandle, MemoryInfo

# 진짜도 handler.py 맨 위에 같은 줄. 예제가 basicConfig(level=INFO)를 켜 둬서 예제 머리말([Producer]/[Consumer])로 찍힌다
logger = logging.getLogger(__name__)


class MaruHandler:
    def __init__(self, config: MaruConfig | None = None):
        self._config = config or MaruConfig()

        self._connected = False

        # 영역을 받고(alloc)·돌려주고(free)·붙고(mmap)·떼는(munmap) 일은 전부 MaruShmClient에게 맡긴다 (1.7)
        # 진짜: MaruHandler → DaxMapper → MaruShmClient 순서로 들고 있다
        self._shm = MaruShmClient()

        # 내 영역(owned region). connect()에서 채워지고 close()에서 비워진다
        #   _owned_handle: 내 영역을 가리키는 핸들 (region_id="psm_…", offset=0, length=영역 전체 크기)
        #   _owned_buf:    내 영역 전체를 보는 창(memoryview). 2장에서 이 창을 마루 Page(1MB)로 잘라 빌려준다
        self._owned_handle: MaruHandle | None = None
        self._owned_buf: memoryview | None = None

        # 내 영역을 마루 Page(chunk_size_bytes)로 나눠 번호를 빌려주는 할당기 (2장). connect()에서 만든다
        #   진짜: OwnedRegionManager가 영역마다 PagedMemoryAllocator를 하나씩 들고 있다 (영역이 하나뿐이라 바로 들고 있음)
        self._allocator: PagedMemoryAllocator | None = None

        # 메타데이터 서버와 이야기하는 창구 (3.4). 진짜: self._rpc = self._make_rpc(server_url)
        #   데이터는 공유 메모리로 직접, 서버에는 위치만 보낸다 ("Metadata traveled, data didn't")
        self._rpc = RpcClient(self._config.server_url, timeout_ms=self._config.timeout_ms)

        # 공유 메모리로 오간 데이터 바이트 (4.3): store한 크기(producer) + retrieve한 view 길이(consumer)
        #   소켓 바이트(self._rpc.bytes_sent/recv)와 나란히 찍어서 "Metadata traveled, data didn't"를 숫자로
        self._data_bytes = 0

    # ---- 연결 / 종료 ---------------------------------------------------------

    def connect(self) -> bool:
        """진짜: 서버 연결 → 서버가 Resource Manager에게 영역을 받아 옴 → 내 영역을 map.

        호두마루: Resource Manager가 없으니 내 영역을 내가 직접 만든다.
          ① 내 영역 만들기 (1장 Region)
          ② 서버 연결 (3장 KVManager · MaruServer)
        """
        if self._connected:  # 이미 연결돼 있으면 그대로 (두 번 불러도 안전)
            return True

        # ① 내 영역 받기: config.pool_size(기본 100MB)만큼.
        #    이름은 안 넘긴다 → 파이썬이 겹치지 않는 이름("psm_…")을 발급 (1.6)
        self._owned_handle = self._shm.alloc(self._config.pool_size)

        # ① 내 영역 열기: alloc이 캐시에 넣어 둔 창을 그대로 돌려받는다
        #    (mmap의 ① 캐시 길 → 내 영역에 창을 두 번 열지 않음, 1.7)
        self._owned_buf = self._shm.mmap(self._owned_handle)

        # ① 내 영역을 Page로 나누기 (2.4). 진짜: owned_region_manager.py 79~85줄 (map 직후)
        #    pool_size는 요청한 크기(config.pool_size)가 아니라 실제로 받은 크기(handle.length)
        #    예: 1000 요청 → 16384 받음(1.2). 요청 크기로 나누면 1000 // 1024 = 0개, 받은 크기면 16개
        self._allocator = PagedMemoryAllocator(
            region_id=self._owned_handle.region_id,
            pool_size=self._owned_handle.length,
            chunk_size=self._config.chunk_size_bytes,
        )

        # ② 서버 연결 + 내 영역 알려 주기 (3.5). 영역 핸들은 connect 때 한 번, 키는 store마다 (3.3)
        #    진짜는 서버가 영역을 나눠 주는 쪽(request_alloc)이라 원래 안다.
        #    호두마루는 Resource Manager가 없어서 producer가 알려 준다 (REGISTER_REGION 0x01)
        #    ZMQ connect는 예약만 해서 서버가 꺼져 있어도 여기선 에러가 안 난다
        #    → register_region에서 timeout → ConnectionError (3.4)
        self._rpc.connect()
        self._rpc.register_region(self._owned_handle)

        self._connected = True
        return True

    def close(self) -> None:
        """진짜: 서버에 연결 해제 알림 + 영역 unmap."""
        if not self._connected:
            return

        # 0) Page 번호 기록 지우기. 할당기는 번호만 관리하고 메모리는 안 건드린다 (메모리는 아래 1)~3))
        self._allocator.close()
        self._allocator = None

        # 1) 내가 들고 있던 창을 반납한다.
        #    빌려 간 조각이 남아 있으면 창을 닫을 수 없다 (1.7 BufferError)
        #    진짜: memory/mapper.py unmap_region의 region.release()
        self._owned_buf.release()
        self._owned_buf = None

        # 2) 창 닫기 (munmap = close).
        #    예제가 아직 들고 있는 조각(handle.buf 등)이 있으면 munmap이 알아서 미룬다 ("deferred to GC")
        self._shm.munmap(self._owned_handle)

        # 3) 영역 돌려주기 (free = unlink, 주인만).
        #    2)에서 창이 캐시에서 빠졌어도 된다: free는 _owned에 따로 기억해 둔
        #    원래 창(track=True, 뒷정리 도우미가 지켜보는 쪽)으로 unlink한다 (1.7)
        self._shm.free(self._owned_handle)
        self._owned_handle = None

        # 3b) 남의 영역 창도 전부 닫기 (4.2b). retrieve에서 붙은 창(producer 영역)이 _mmap_cache에 남아 있으면
        #     프로세스가 끝날 때 SharedMemory.__del__이 닫으려다 BufferError ("Exception ignored")
        #     munmap이 조각이 남은 창은 미뤄 준다 ("deferred to GC", 1.7)
        #     진짜: handler.close 3단계 "Unmap all regions (owned + shared)"
        self._shm.close()

        # 3c) 4.3 측정 결과: 소켓으로 오간 바이트 vs 공유 메모리로 오간 데이터 바이트
        sent, recv = self._rpc.bytes_sent, self._rpc.bytes_recv
        logger.info(
            "Metadata traveled, data didn't — socket %d bytes (sent %d + recv %d), shared memory data %d bytes",
            sent + recv, sent, recv, self._data_bytes,
        )

        # 4) 서버 연결 닫기. 진짜는 서버에 연결 해제를 알려 내 영역을 돌려준다 (지연 해제, 6장)
        self._rpc.close()

        self._connected = False
    # ---- 데이터 경로 ---------------------------------------------------------

    def alloc(self, size: int) -> AllocHandle:
        """내 영역에서 페이지 하나를 빌려, 쓰기 가능한 창(buf)을 돌려준다.

        진짜: handler.py alloc (528~558줄). MaruShmClient.alloc(영역 받기)과 다른 층: 이건 Page 한 칸 빌리기
        """
        chunk_size = self._config.chunk_size_bytes

        # 1) 입구에서 막기: Page보다 큰 데이터는 넘친다 (2.1)
        if size > chunk_size:
            raise ValueError(f"Requested size {size} exceeds chunk_size {chunk_size}")

        # 2) Page 번호 빌리기. None = 다 떨어짐 → 어떻게 할지는 여기서 정한다 (2.2)
        #    진짜는 _expand_region()으로 영역을 하나 더 받아 본 뒤 안 되면 에러 (7장). 호두마루는 영역 1개라 바로 에러
        page_index = self._allocator.allocate()
        if page_index is None:
            raise ValueError("Cannot allocate page: pool exhausted")

        # 3) 번호 → 영역 안 위치. MaruHandle.offset(영역 시작, 항상 0)과 다른 층의 offset
        #    0으로 고정하면 모든 키가 맨 앞 1MB를 덮어쓴다
        offset = page_index * chunk_size

        # 4) 창은 size만큼만. Page는 통째로 빌리지만, chunk_size로 자르면 작은 데이터에서
        #    buf[:] = data가 ValueError (2.4 실험: b[4:8][:] = b"AB")
        #    진짜: get_buffer_view(region_id, page_index * chunk_size, size)
        buf = self._owned_buf[offset : offset + size]

        return AllocHandle(
            buf=buf,
            region_id=self._owned_handle.region_id,
            page_index=page_index,
            size=size,
        )

    def store(self, key: str, handle: AllocHandle) -> bool:
        """데이터는 이미 handle.buf에 써져 있다. 서버에 '키 → 위치'만 등록한다 (3.5).

        진짜: handler.py store (621~708줄). 진짜의 로컬 중복 확인(_key_to_location)과
        exists_kv로 먼저 묻기는 뺐다 (서버의 "먼저 등록한 쪽이 이김"만으로 결과는 같다)

        key: 진짜 시그니처는 str인데 예제는 1001(int)을 넘긴다 → 그대로 보낸다 (진짜도 바꾸지 않음).
             msgpack·dict는 int도 받는다. 대신 producer와 consumer가 같은 타입을 써야 같은 키가 된다
        """
        # 장부에 적을 위치: Page 번호 → 영역 안 위치 (2.4 alloc과 같은 계산)
        kv_offset = handle.page_index * self._config.chunk_size_bytes

        try:
            is_new = self._rpc.register_kv(
                key=key,
                region_id=handle.region_id,
                kv_offset=kv_offset,
                kv_length=handle.size,  # 키마다 다른 길이 → 핸들이 아니라 장부에 (1.6)
            )
        except ConnectionError:
            # 등록 못 함 (서버 꺼짐 → timeout, 3.4) → 아무도 이 Page를 찾을 수 없으니 돌려준다
            self._allocator.free(handle.page_index)
            return False

        if not is_new:
            # 같은 키를 다른 producer가 먼저 등록함 (먼저 등록한 쪽이 이김, 3.1)
            # 내 Page는 장부에 없는 복사본 → 안 돌려주면 Page 누수
            # 진짜: "key=%s lost register race, freed page" (PR #94가 배치 버전에서 고친 것)
            self._allocator.free(handle.page_index)
        self._data_bytes += handle.size  # 4.3: 데이터는 이미 handle.buf로 공유 메모리에 써졌다 (소켓 X)
        return True  # 진짜와 같이: 이미 있던 키도 "저장됨" (같은 키 = 같은 내용)

    def retrieve(self, key: str) -> MemoryInfo | None:
        """서버에 위치를 묻고, 그 영역에 붙어서 복사 없이 읽을 창(view)을 돌려준다 (4.1).

        진짜: handler.py retrieve (709~800줄)
        주의 (진짜 docstring과 같음): 돌려준 view는 영역이 열려 있는 동안만 유효하다. close() 뒤에는 쓰지 말 것
        """
        # 1) 서버에 "이 키 어디 있어?" → 소켓으로 오가는 건 위치(수백 바이트)뿐, 데이터는 안 온다
        result = self._rpc.lookup_kv(key)
        if result is None:
            return None  # 없는 키 → consumer.py가 "key=… not found" 출력

        # 2) 그 영역의 창. 진짜는 is_owned로 먼저 갈라서 남의 영역일 때만 map_region을 하지만,
        #    호두마루 mmap은 두 길이라 확인 없이 불러도 된다 (1.7)
        #      ① 캐시에 있으면 그 창 (내 영역 = alloc이 넣어 둔 창, 또는 이미 붙은 남의 영역)
        #      ② 없으면 이름으로 붙기 (남의 영역 처음, track=False)
        handle = result["handle"]  # MaruHandle (3.4 lookup_kv에서 from_dict로 바꿔 둔 것)
        region_buf = self._shm.mmap(handle)  # 영역 전체 창 (100MB)

        # 3) 키 하나만큼 자르기. 시작 = 장부의 kv_offset (Page 번호 × chunk_size, 3.5 store에서 적은 값)
        #    [:kv_length]로 자르면 시작이 늘 0 → 모든 키가 Page 0 (key=1001의 'A')을 읽는다
        #    진짜: get_buffer_view(region_id, result.kv_offset, result.kv_length)
        kv_offset = result["kv_offset"]
        view = region_buf[kv_offset : kv_offset + result["kv_length"]]
        self._data_bytes += len(view)  # 4.3: 복사 없이 넘겨준 데이터 크기 (소켓 X)
        return MemoryInfo(view=view)

    # ---- with 문 (진짜와 동일) -----------------------------------------------

    def __enter__(self) -> "MaruHandler":
        if self._config.auto_connect:
            self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
