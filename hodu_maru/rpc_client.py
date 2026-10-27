"""RpcClient — 진짜: maru_handler/rpc_client.py + rpc_client_base.py

손으로 치던 ask()를 handler가 대신 하게 해 주는 창구.
클라이언트의 register_kv를 부르면 소켓 건너편에서 서버의 register_kv가 불린다 = RPC(원격 함수 호출)

    producer / consumer
       │  alloc · store · retrieve                       ← handler의 메서드 (예제가 부르는 것)
       ▼
    MaruHandler
       │  register_region · register_kv · lookup_kv      ← RpcClient의 메서드 (서버에 부탁)
       ▼
    RpcClient ──REQ 소켓──▶ RpcServer → MaruServer.register_region / register_kv / lookup_kv
"""

import msgpack
import zmq

from hodu_maru.protocol import MessageType
from hodu_maru.types import MaruHandle


class RpcClient:
    def __init__(self, server_url: str = "tcp://localhost:5555", timeout_ms: int = 5000):
        self._server_url = server_url
        self._timeout_ms = timeout_ms  # 서버가 답을 안 할 때 얼마나 기다릴지 (밀리초, 진짜 기본값도 5000)
        self._context: zmq.Context | None = None
        self._socket: zmq.Socket | None = None
        # 소켓으로 오간 바이트 (4.3). msgpack으로 바꾼 뒤의 bytes 길이 = 실제로 소켓에 실린 메시지 크기
        #   (ZMQ가 붙이는 프레임 머리 몇 바이트·연결 인사는 안 셈)
        self.bytes_sent = 0
        self.bytes_recv = 0

    def connect(self) -> None:
        """서버에 연결. ZMQ의 connect는 '여기로 연결해 둬'라고 예약만 하고 바로 돌아온다 (3.4 실험)"""
        self._context = zmq.Context()
        self._socket = self._context.socket(zmq.REQ)
        self._socket.setsockopt(zmq.LINGER, 0)  # 닫을 때 못 보낸 메시지를 기다리지 않음
        self._socket.connect(self._server_url)

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        if self._context is not None:
            self._context.term()
            self._context = None

    def _send_request(self, msg_type: MessageType, data: dict) -> dict:
        """번호와 내용을 보내고 답을 받는다. 손으로 치던 ask()가 이것 (3.4). 진짜: rpc_client.py 69~113줄

        서버가 꺼져 있어도 connect·send는 에러 없이 지나가고 recv만 영원히 멈춘다 (3.4 실험)
        → 정해진 시간만 기다리고, 넘으면 포기하고 소켓을 새로 만든다
        """
        request = {"msg_type": msg_type, **data}  # 번호와 내용을 dict 하나로 (서버가 req["msg_type"]으로 읽음)
        payload = msgpack.packb(request)  # ① dict → bytes
        self.bytes_sent += len(payload)  # 4.3: 소켓에 실리는 건 bytes. len(request)는 dict 칸 수라 바이트가 아니다
        self._socket.send(payload)  # 보내기 (내 쪽 대기열에 넣기만, 멈추지 않음)

        poller = zmq.Poller()
        poller.register(self._socket, zmq.POLLIN)  # "이 소켓에 받을 게 오면 알려 줘"
        events = dict(poller.poll(self._timeout_ms))  # 최대 timeout_ms만 기다린다 (None이면 영원히, 0이면 안 기다림)

        if self._socket not in events:  # 시간 안에 답이 없으면
            # 이 REQ 소켓은 "보냈는데 답을 못 받은" 상태에 갇혔다 → 다음 send는
            # ZMQError: Operation cannot be accomplished in current state (3.3과 같은 에러)
            self._reset_socket()
            return {"error": "timeout", "success": False}  # 진짜와 같은 모양 → register_kv가 ConnectionError로 바꿈

        raw = self._socket.recv(zmq.NOBLOCK)  # ② 답이 이미 와 있으니 recv가 멈추지 않음
        self.bytes_recv += len(raw)  # 4.3: 소켓으로 들어온 바이트
        return msgpack.unpackb(raw)

    def _reset_socket(self) -> None:
        """갇힌 REQ 소켓을 버리고 새로 만든다. 진짜 주석: "REQ socket needs reset after timeout"

        덤: 늦게 도착한 이전 요청의 답도 옛 소켓과 같이 버려져서, 새 요청의 답과 헷갈릴 일이 없다
        """
        self._socket.close()
        self._socket = self._context.socket(zmq.REQ)  # 클라이언트는 묻는 쪽 = REQ
        self._socket.setsockopt(zmq.LINGER, 0)
        self._socket.connect(self._server_url)

    # ---- 서버에 부탁하는 메서드 (이름이 서버 쪽 MaruServer와 같다) ----------------

    def register_region(self, handle: MaruHandle) -> bool:
        response = self._send_request(MessageType.REGISTER_REGION, {"handle": handle.to_dict()})
        if "error" in response:
            raise ConnectionError(f"register_region RPC failed: {response['error']}")
        return response.get("success", False)

    def register_kv(self, key: str, region_id: str, kv_offset: int, kv_length: int) -> bool:
        """진짜 rpc_client_base.py 161~186줄과 같은 모양"""
        response = self._send_request(
            MessageType.REGISTER_KV,
            {"key": key, "region_id": region_id, "kv_offset": kv_offset, "kv_length": kv_length},
        )
        if "error" in response:
            raise ConnectionError(f"register_kv RPC failed: {response['error']}")
        return response.get("is_new", False)

    def lookup_kv(self, key: str) -> dict | None:
        """없으면 None, 있으면 서버 쪽 lookup_kv와 같은 모양 {"handle": MaruHandle, "kv_offset", "kv_length"}"""
        response = self._send_request(MessageType.LOOKUP_KV, {"key": key})
        if not response.get("found", False):
            return None
        return {
            "handle": MaruHandle.from_dict(response["handle"]),  # dict → MaruHandle (3.3 to_dict의 반대)
            "kv_offset": response["kv_offset"],
            "kv_length": response["kv_length"],
        }
