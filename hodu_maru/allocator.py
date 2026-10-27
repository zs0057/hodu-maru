"""PagedMemoryAllocator — 진짜: maru_handler/memory/allocator.py

내 영역(owned region)을 chunk_size 크기의 마루 Page로 나누고, Page 번호를 빌려주고(allocate) 돌려받는다(free).
읽기/쓰기는 하지 않는다. 번호만 관리하고, 주소 계산(offset = page_index × chunk_size)과 데이터 접근은 handler가 한다 (2.4).
"""

from collections import deque


class PagedMemoryAllocator:
    def __init__(self, region_id: str, pool_size: int, chunk_size: int):
        # region_id: 진짜는 int. 호두마루는 OS 이름(str, "psm_…")을 쓴다 (1.6). 할당기는 기록만 하고 쓰지 않는다
        if chunk_size <= 0:
            raise ValueError(f"chunk_size must be positive, got {chunk_size}")

        self._region_id = region_id
        self._chunk_size = chunk_size
        self._pool_size = pool_size

        # Page 개수는 내림: 자투리는 버린다 (2.1)
        #   반쪽 Page를 만들면 chunk_size만큼 쓸 때 영역 밖으로 넘친다
        #   모든 Page가 같은 크기라서 할당기는 크기 없이 번호만 들고 있으면 된다
        self._page_count = self._pool_size // self._chunk_size
        if self._page_count == 0:
            raise ValueError(
                f"Pool size {self._pool_size} is smaller than chunk_size {self._chunk_size}"
            )

        # free list: 빌려줄 수 있는 Page 번호. 처음엔 전부 (0 ~ page_count-1, range는 끝을 안 넣음)
        #   왼쪽에서 빌려주고(popleft) 오른쪽으로 돌려받는다(append). 둘 다 O(1)
        self._free_pages: deque[int] = deque(range(self._page_count))

        # 빌려준 번호. deque는 같은 번호가 두 번 들어가도 막지 않으므로 따로 적어 double free를 막는다
        self._allocated_pages: set[int] = set()

        self._num_allocated = 0

    @property
    def chunk_size(self) -> int:
        return self._chunk_size

    @property
    def page_count(self) -> int:
        return self._page_count

    @property
    def num_free_pages(self) -> int:
        return len(self._free_pages)

    @property
    def num_allocated(self) -> int:
        return self._num_allocated

    def allocate(self) -> int | None:
        """Page 하나를 빌려준다. 다 떨어지면 None.

        None인 이유: Page가 떨어지는 건 버그가 아니라 흔한 상황이라, 어떻게 할지는 부르는 쪽이 정한다
        (진짜 handler는 영역을 하나 더 받아 보고, 안 되면 그때 에러를 던진다)
        """
        try:
            page_index = self._free_pages.popleft()  # pop이면 오른쪽 끝(99)부터 나온다
        except IndexError:
            return None

        self._allocated_pages.add(page_index)
        self._num_allocated += 1
        return page_index

    def free(self, page_index: int) -> None:
        """Page를 돌려받는다."""
        # ① 있을 수 없는 번호. 이게 없어도 ②에 걸리지만 메시지가 "Double free"로 틀리게 나온다
        if page_index < 0 or page_index >= self._page_count:
            raise ValueError(
                f"Invalid page_index: {page_index} (range: 0-{self._page_count - 1})"
            )
        # ② 빌려준 적 없는 번호 = 두 번 돌려줌. 이게 없으면 같은 Page를 두 키에게 빌려줘서 에러 없이 덮어쓴다
        if page_index not in self._allocated_pages:
            raise ValueError(f"Double free detected: page {page_index} is not allocated")

        self._allocated_pages.discard(page_index)  # set.pop()은 인자 없이 아무거나 꺼낸다 → 특정 번호는 discard
        self._free_pages.append(page_index)
        self._num_allocated -= 1

    def get_stats(self) -> dict:
        return {
            "pool_size": self._pool_size,
            "chunk_size": self._chunk_size,
            "page_count": self._page_count,
            "free_pages": len(self._free_pages),
            "allocated_pages": self._num_allocated,
            "utilization": self._num_allocated / self._page_count,
        }

    def close(self) -> None:
        """번호 기록만 지운다. 메모리를 닫는 건 handler.close() → MaruShmClient의 일 (1.8)"""
        self._free_pages.clear()
        self._allocated_pages.clear()
        self._num_allocated = 0
