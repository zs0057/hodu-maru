"""MaruServer + RpcServer — 진짜: maru_server/server.py, rpc_server.py, rpc_handler_mixin.py

메타데이터만 다루는 서버. 데이터(KV)는 절대 건드리지 않는다: 위치를 적고, 물으면 알려 줄 뿐이다.
실행: python -m hodu_maru.server

    connect()    → "내 영역은 psm_abc, 크기 100MB"  → 영역 목록   (REGISTER_REGION 0x01)
    store(1001)  → "1001은 psm_abc의 0MB부터 1MB"   → KVManager  (REGISTER_KV 0x10)
    lookup(1001) → 두 장부를 합쳐 "영역 핸들 + 위치"              (LOOKUP_KV 0x11)
"""

import logging

import msgpack
import zmq

from hodu_maru.kv_manager import KVManager
from hodu_maru.protocol import MessageType
from hodu_maru.types import MaruHandle

logger = logging.getLogger(__name__)


# ---- MaruServer: 장부 두 개를 들고 있는 두뇌 (진짜: server.py) -------------------


class MaruServer:
    def __init__(self):
        # 장부 1: 키 → 위치 (KVEntry: region_id, kv_offset, kv_length). 진짜 모양 그대로
        self._kv_manager = KVManager()

        # 장부 2: 영역 목록 region_id → MaruHandle
        #   consumer가 붙으려면 MaruHandle(region_id, offset, length)가 필요한데 KVEntry엔 region_id뿐이라서 (3.3 설계)
        #   KVEntry에 영역 크기를 넣으면 같은 값을 키마다 반복한다
        #   진짜: AllocationManager의 AllocationInfo.handle
        #   (owner_instance_id, kv_ref_count, owner_connected는 지연 해제용이라 6장)
        self._regions: dict[str, MaruHandle] = {}

    def register_region(self, handle: MaruHandle) -> bool:
        """producer가 connect()에서 자기 영역을 알려 준다. 영역 핸들은 connect 때 한 번, 키는 store마다"""
        self._regions[handle.region_id] = handle
        return True

    def register_kv(self, key: str, region_id: str, kv_offset: int, kv_length: int) -> bool:
        """키를 장부에 적는다. 진짜는 두 번째 반환값으로 영역의 kv_ref_count를 +1 하지만 그건 6장"""
        is_new, _alloc_to_ref = self._kv_manager.register(key, region_id, kv_offset, kv_length)
        return is_new

    def lookup_kv(self, key: str) -> dict | None:
        """두 장부를 합쳐 '영역 핸들 + 위치'를 돌려준다. 진짜 server.py lookup_kv와 같은 모양"""
        entry = self._kv_manager.lookup(key)
        if entry is None:  # 없는 키
            return None
        handle = self._regions.get(entry.region_id)
        if handle is None:  # 키는 있는데 영역이 없음 (보통 영역이 이미 사라진 경우. 장부 정리는 6장)
            return None
        return {"handle": handle, "kv_offset": entry.kv_offset, "kv_length": entry.kv_length}


# ---- RpcServer: 소켓으로 받은 요청을 MaruServer로 넘기는 창구 (진짜: rpc_server.py) ----


class RpcServer:
    def __init__(self, server: MaruServer, host: str = "127.0.0.1", port: int = 5555):
        self._server = server
        self._host = host
        self._port = port
        self._context: zmq.Context | None = None
        self._socket: zmq.Socket | None = None
        self._running = False

    @property
    def address(self) -> str:
        return f"tcp://{self._host}:{self._port}"

    # 번호 → 처리 함수. 진짜: rpc_handler_mixin.py _get_handlers / _handle_message
    def _handle_message(self, msg_type: int, req: dict) -> dict:
        handlers = {
            MessageType.REGISTER_REGION: self._handle_register_region,
            MessageType.REGISTER_KV: self._handle_register_kv,
            MessageType.LOOKUP_KV: self._handle_lookup_kv,
        }
        handler = handlers.get(msg_type)
        if handler is None:
            # 모르는 번호여도 죽지 않고 답한다. REP는 받았으면 반드시 send해야 다음 recv를 할 수 있다 (3.3)
            return {"error": f"Unknown message type: {msg_type}"}
        return handler(req)

    def _handle_register_region(self, req: dict) -> dict:
        handle = MaruHandle.from_dict(req["handle"])  # dict → MaruHandle (msgpack은 객체를 못 보낸다)
        self._server.register_region(handle)
        return {"success": True}

    def _handle_register_kv(self, req: dict) -> dict:
        is_new = self._server.register_kv(
            key=req["key"],
            region_id=req["region_id"],
            kv_offset=req["kv_offset"],
            kv_length=req["kv_length"],
        )
        return {"success": True, "is_new": is_new}  # 진짜와 같은 모양

    def _handle_lookup_kv(self, req: dict) -> dict:
        result = self._server.lookup_kv(key=req["key"])
        if result is None:
            # None을 그대로 보내면 "없음"인지 "이상한 답"인지 구분이 안 된다 → found 칸으로 분명히
            return {"found": False}
        return {
            "found": True,
            "handle": result["handle"].to_dict(),  # MaruHandle → dict (3.3: msgpack은 기본 타입만)
            "kv_offset": result["kv_offset"],
            "kv_length": result["kv_length"],
        }

    def start(self) -> None:
        self._context = zmq.Context()
        self._socket = self._context.socket(zmq.REP)
        # 100ms마다 recv에서 깨어나 종료 신호(Ctrl+C)를 볼 수 있게. 진짜와 같음
        #   이게 없으면 recv에서 영원히 멈춰 종료 신호를 못 본다 (3.3)
        self._socket.setsockopt(zmq.RCVTIMEO, 100)
        self._socket.setsockopt(zmq.LINGER, 0)  # 닫을 때 남은 메시지를 기다리지 않음
        self._socket.bind(self.address)
        self._running = True
        logger.info("RPC Server started on %s", self.address)

        while self._running:
            try:
                raw = self._socket.recv()  # REP: recv → send → recv … 순서 고정
            except zmq.Again:  # 100ms 동안 요청 없음 → 다시 기다림
                continue
            try:
                req = msgpack.unpackb(raw)  # bytes → dict
                response = self._handle_message(req.get("msg_type"), req)
            except Exception:
                logger.error("Error handling message", exc_info=True)
                response = {"error": "internal server error"}  # 에러가 나도 답은 보낸다 (안 보내면 클라이언트가 영원히 멈춘다)
            self._socket.send(msgpack.packb(response))  # dict → bytes

    def stop(self) -> None:
        self._running = False
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        if self._context is not None:
            self._context.term()
            self._context = None
        logger.info("RPC Server stopped")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [Server] %(message)s")
    rpc = RpcServer(MaruServer())
    try:
        rpc.start()
    except KeyboardInterrupt:  # Ctrl+C
        pass
    finally:
        rpc.stop()


if __name__ == "__main__":
    main()
