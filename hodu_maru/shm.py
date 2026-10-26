"""MaruShmClient — 진짜: maru_shm/client.py

영역을 받고(alloc), 돌려주고(free), 붙고(mmap), 떼는(munmap) 일만 한다.
진짜는 Resource Manager에게 요청하지만, 호두마루는 OS 공유 메모리를 직접 쓴다.
"""

from multiprocessing import shared_memory

from hodu_maru.types import MaruHandle


class MaruShmClient:
    def __init__(self):
        # region_id -> 열린 창. 진짜도 _mmap_cache에 region_id별 창을 보관한다
        self._mmap_cache: dict[str, shared_memory.SharedMemory] = {}
        # region_id -> 내가 만든 원래 창 (track=True, 뒷정리 도우미가 지켜보는 쪽).
        # munmap으로 _mmap_cache에서 빠져도 free(unlink)를 이 창으로 해야 도우미 기록도 같이 지워진다.
        # 진짜도 내 영역(OwnedRegionManager)과 열린 창(DaxMapper)을 따로 관리한다
        self._owned: dict[str, shared_memory.SharedMemory] = {}

    def alloc(self, size: int) -> MaruHandle:
        """영역을 새로 받는다.

        진짜와 달리 만들자마자 창도 열리므로, 그 창을 캐시에 넣어 둔다 (1.7 선택 ②).
        이름은 안 넘긴다 → 파이썬이 겹치지 않는 이름("psm_…")을 발급한다 (1.6).
        """
        shm = shared_memory.SharedMemory(create=True, size=size)
        self._mmap_cache[shm.name] = shm
        self._owned[shm.name] = shm  # munmap해도 원래 창을 잊지 않게
        return MaruHandle(region_id=shm.name, offset=0, length=shm.size)

    def free(self, handle: MaruHandle) -> None:
        """영역을 돌려준다. 주인만 할 수 있다 (진짜: non-root clients can only free their own allocations)"""
        shm = self._owned.pop(handle.region_id, None)
        if shm is None:
            raise ValueError(f"내가 만든 영역이 아니라서 free할 수 없다: {handle.region_id}")
        shm.unlink()  # 1.5 (b): 이름을 지운다. 창이 닫힌 뒤에도 된다. 지켜보는 쪽 창이라 도우미 기록도 같이 지워진다

    def mmap(self, handle: MaruHandle) -> memoryview:
        """영역에 붙어서 창을 연다. 이미 열려 있으면 그 창을 돌려준다.

        진짜는 mmap 객체를 돌려주고 DaxMapper가 memoryview로 감싸지만,
        호두마루는 바로 memoryview(영역 전체)를 돌려준다. 키 하나만큼 자르는 건 4장 retrieve.
        """
        shm = self._mmap_cache.get(handle.region_id)  # ① 이미 열린 창이 있나 (진짜: Fast path)
        if shm is None:  # ② 없으면 남의 영역 → 붙는다 (1.3)
            # track=False: 붙기만 한 쪽은 지울 권리가 없다. True면 내 프로세스가 끝날 때 영역이 unlink된다 (발견 로그, 1.9)
            shm = shared_memory.SharedMemory(name=handle.region_id, track=False)
            self._mmap_cache[handle.region_id] = shm
        return shm.buf[handle.offset : handle.offset + handle.length]  # 1.6 "넣었으면 쓴다"

    def munmap(self, handle: MaruHandle) -> None:
        """창을 닫는다. 진짜: maru_shm/client.py munmap + memory/mapper.py unmap_region

        진짜의 with self._lock은 스레드 1개라 뺐다.
        """
        shm = self._mmap_cache.pop(handle.region_id, None)  # 꺼내면서 지우기. 없으면 None → 두 번 불러도 안전
        if shm is None:
            return
        try:
            shm.close()  # 1.5 (a): 내 창만 닫는다
        except BufferError:
            # 빌려 간 조각(view)이 아직 있다 → 닫기를 미룬다 (진짜: "munmap deferred to GC")
            # 그냥 두면 SharedMemory.__del__이 다시 close를 시도해 경고가 뜬다.
            # mmap을 SharedMemory에서 떼어 내면, 조각이 사라질 때 mmap이 스스로 풀린다 (진짜는 날것의 mmap을 들고 있어서 원래 이렇게 동작)
            shm._mmap = None
            shm.close()  # 남은 fd만 닫는다
