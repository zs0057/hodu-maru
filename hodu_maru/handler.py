"""MaruHandler — 진짜: maru_handler/handler.py (약 1500줄 → 여기선 수십 줄이 목표)

예제가 부르는 것: MaruHandler(config), with 문, alloc(size), store(key, handle), retrieve(key).
몸통은 장마다 같이 채운다. NotImplementedError 메시지가 "다음에 만들 것"이다.
"""

from hodu_maru.config import MaruConfig
from hodu_maru.shm import MaruShmClient
from hodu_maru.types import AllocHandle, MaruHandle, MemoryInfo


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

        # ② 서버 연결: 3장에서 여기에 추가

        self._connected = True
        return True

    def close(self) -> None:
        """진짜: 서버에 연결 해제 알림 + 영역 unmap."""
        if not self._connected:
            return
        
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

        self._connected = False
    # ---- 데이터 경로 ---------------------------------------------------------

    def alloc(self, size: int) -> AllocHandle:
        """내 영역에서 페이지 하나를 빌려, 쓰기 가능한 창(buf)을 돌려준다."""
        raise NotImplementedError("2장 PagedMemoryAllocator: 페이지 할당기")

    def store(self, key: str, handle: AllocHandle) -> bool:
        """데이터는 이미 handle.buf에 써져 있다. 서버에 '키 → 위치'만 등록한다.

        메모: 진짜 시그니처는 key: str인데 예제는 1001(int)을 넘긴다. 3장에서 짚기.
        """
        raise NotImplementedError("3장 KVManager · MaruServer: 서버에 등록")

    def retrieve(self, key: str) -> MemoryInfo | None:
        """서버에 위치를 묻고, 그 영역에 붙어서 복사 없이 읽을 창(view)을 돌려준다."""
        raise NotImplementedError("4장 retrieve: 위치 조회 + 남의 영역에 붙기")

    # ---- with 문 (진짜와 동일) -----------------------------------------------

    def __enter__(self) -> "MaruHandler":
        if self._config.auto_connect:
            self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
