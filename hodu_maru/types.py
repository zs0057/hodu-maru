"""MaruHandle — 진짜: maru_shm/types.py
AllocHandle, MemoryInfo — 진짜: maru_handler/memory/types.py
"""

from dataclasses import dataclass

@dataclass
class MaruHandle:
    """영역에 붙기 위한 정보. 진짜: maru_shm/types.py"""

    region_id: str    # 진짜는 int. Resource Manager가 없어서 OS 이름(str)을 그대로 쓴다. 예: "psm_91a47b86"
    offset: int = 0   # 공유 메모리 안에서 영역이 시작하는 위치. 공유 메모리 1개 = 영역 1개라 항상 0 (진짜 FS_DAX와 같음)
    length: int = 0   # 영역 전체 크기 (OS 페이지 단위로 올림). 키별 데이터 길이는 서버 장부의 kv_length
    # auth_token 없음: 이름만 알면 누구나 붙어서 읽고 쓸 수 있다 (접근 제어 포기, 학습용 맥 1대라서)

    # msgpack은 dict·str·int 같은 기본 타입만 안다 → 소켓으로 보낼 땐 dict로 바꾼다 (3.3)
    #   서버: MaruHandle → to_dict() → dict → packb → bytes ──소켓──▶
    #   클라: bytes → unpackb → dict → from_dict() → MaruHandle → mmap(handle)
    # 진짜도 같은 이름 (maru_shm/types.py). 호두마루는 auth_token 없이 3칸
    def to_dict(self) -> dict:
        return {"region_id": self.region_id, "offset": self.offset, "length": self.length}

    @classmethod
    def from_dict(cls, d: dict) -> "MaruHandle":
        return cls(region_id=d["region_id"], offset=d.get("offset", 0), length=d.get("length", 0))

@dataclass(eq=False)
class AllocHandle:
    """alloc()이 돌려주는 것.

    호출자가 buf에 직접 쓰고, store(key, handle)로 등록한다 (복사 없음).
    """

    buf: memoryview  # 내 영역 안 페이지 하나를 가리키는 쓰기 가능한 창
    region_id: str    # 진짜는 int. Resource Manager가 없어서 OS 이름(str)을 그대로 쓴다. 예: "psm_91a47b86"
    page_index: int  # 영역 안에서 몇 번째 페이지인가
    size: int  # 요청한 크기 (페이지 크기 이하)


@dataclass
class MemoryInfo:
    """retrieve()가 돌려주는 것.

    view는 데이터가 있는 영역(남의 영역일 수도 있음)을 직접 가리킨다 (복사 없음).
    """

    view: memoryview
