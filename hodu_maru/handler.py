"""MaruHandler — 진짜: maru_handler/handler.py (약 1500줄 → 여기선 수십 줄이 목표)

예제가 부르는 것: MaruHandler(config), with 문, alloc(size), store(key, handle), retrieve(key).
몸통은 장마다 같이 채운다. NotImplementedError 메시지가 "다음에 만들 것"이다.
"""

from hodu_maru.config import MaruConfig
from hodu_maru.types import AllocHandle, MemoryInfo


class MaruHandler:
    def __init__(self, config: MaruConfig | None = None):
        self._config = config or MaruConfig()
        self._connected = False

    # ---- 연결 / 종료 ---------------------------------------------------------

    def connect(self) -> bool:
        """진짜: 서버 연결 → 서버가 Resource Manager에게 영역을 받아 옴 → 내 영역을 map.

        호두마루: Resource Manager가 없으니 내 영역을 내가 직접 만든다.
          ① 내 영역 만들기 (1장 Region)
          ② 서버 연결 (3장 KVManager · MaruServer)
        """
        raise NotImplementedError("1장 Region: connect()에서 내 영역을 만든다")

    def close(self) -> None:
        """진짜: 서버에 연결 해제 알림 + 영역 unmap."""
        if not self._connected:
            return
        raise NotImplementedError("1장 Region: close()에서 내 영역을 정리한다")

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
