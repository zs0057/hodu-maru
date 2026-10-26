"""hodu-maru — Maru(xcena-dev/maru)를 공부하려고 만드는 미니 Maru.

진짜: maru/__init__.py — 바깥에 보이는 이름만 다시 내보낸다.
"""

from hodu_maru.config import MaruConfig
from hodu_maru.handler import MaruHandler
from hodu_maru.types import AllocHandle, MemoryInfo

__all__ = ["AllocHandle", "MaruConfig", "MaruHandler", "MemoryInfo"]
