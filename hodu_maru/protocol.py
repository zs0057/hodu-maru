"""메시지 번호 — 진짜: maru_common/protocol.py의 MessageType

요청 dict의 "msg_type" 칸에 이 번호를 넣으면, 서버가 번호를 보고 어떤 함수를 부를지 고른다.
"""

from enum import IntEnum


class MessageType(IntEnum):
    # 영역 (0x01~0x0F)
    #   진짜 REQUEST_ALLOC(0x01) 자리. 진짜는 서버가 영역을 나눠 주는 쪽이라 원래 알고,
    #   호두마루는 Resource Manager가 없어서 producer가 connect()에서 자기 영역을 알려 준다
    REGISTER_REGION = 0x01

    # KV (0x10~0x1F) — 진짜와 같은 번호
    REGISTER_KV = 0x10  # store(): "이 키는 이 영역의 여기부터 몇 바이트"
    LOOKUP_KV = 0x11  # retrieve(): "이 키 어디 있어?"
