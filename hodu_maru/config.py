"""MaruConfig — 진짜: maru_common/config.py

진짜에는 필드가 30개 넘게 있다. 예제가 쓰는 3개 + 페이지 크기 + auto_connect만 남겼다.
이름과 기본값은 진짜와 같다.
"""

from dataclasses import dataclass


@dataclass
class MaruConfig:
    server_url: str = "tcp://localhost:5555"  # 메타데이터 서버 주소
    instance_id: str | None = None  # 나는 누구인가 (producer / consumer)
    pool_size: int = 1024 * 1024 * 100  # 내 영역 크기 (100MB)
    chunk_size_bytes: int = 1024 * 1024  # 페이지 1개 크기 (1MB)
    auto_connect: bool = True  # with 문에 들어갈 때 connect()를 부를지
