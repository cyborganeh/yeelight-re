"""Minimal pure-Python AES-128 with CBC and PKCS#7 padding.

The miIO protocol encrypts its JSON payloads with AES-128-CBC. The rest of this
project has no third-party dependencies, so this small implementation exists
instead of pulling in ``cryptography``/``pycryptodome``.

It is only used for a handful of short control packets. It is **not**
constant-time and must not be used to protect secrets at rest or in transit
against a motivated attacker.
"""

from __future__ import annotations

SBOX = bytes(
    [
        0x63, 0x7C, 0x77, 0x7B, 0xF2, 0x6B, 0x6F, 0xC5, 0x30, 0x01, 0x67, 0x2B, 0xFE, 0xD7, 0xAB, 0x76,
        0xCA, 0x82, 0xC9, 0x7D, 0xFA, 0x59, 0x47, 0xF0, 0xAD, 0xD4, 0xA2, 0xAF, 0x9C, 0xA4, 0x72, 0xC0,
        0xB7, 0xFD, 0x93, 0x26, 0x36, 0x3F, 0xF7, 0xCC, 0x34, 0xA5, 0xE5, 0xF1, 0x71, 0xD8, 0x31, 0x15,
        0x04, 0xC7, 0x23, 0xC3, 0x18, 0x96, 0x05, 0x9A, 0x07, 0x12, 0x80, 0xE2, 0xEB, 0x27, 0xB2, 0x75,
        0x09, 0x83, 0x2C, 0x1A, 0x1B, 0x6E, 0x5A, 0xA0, 0x52, 0x3B, 0xD6, 0xB3, 0x29, 0xE3, 0x2F, 0x84,
        0x53, 0xD1, 0x00, 0xED, 0x20, 0xFC, 0xB1, 0x5B, 0x6A, 0xCB, 0xBE, 0x39, 0x4A, 0x4C, 0x58, 0xCF,
        0xD0, 0xEF, 0xAA, 0xFB, 0x43, 0x4D, 0x33, 0x85, 0x45, 0xF9, 0x02, 0x7F, 0x50, 0x3C, 0x9F, 0xA8,
        0x51, 0xA3, 0x40, 0x8F, 0x92, 0x9D, 0x38, 0xF5, 0xBC, 0xB6, 0xDA, 0x21, 0x10, 0xFF, 0xF3, 0xD2,
        0xCD, 0x0C, 0x13, 0xEC, 0x5F, 0x97, 0x44, 0x17, 0xC4, 0xA7, 0x7E, 0x3D, 0x64, 0x5D, 0x19, 0x73,
        0x60, 0x81, 0x4F, 0xDC, 0x22, 0x2A, 0x90, 0x88, 0x46, 0xEE, 0xB8, 0x14, 0xDE, 0x5E, 0x0B, 0xDB,
        0xE0, 0x32, 0x3A, 0x0A, 0x49, 0x06, 0x24, 0x5C, 0xC2, 0xD3, 0xAC, 0x62, 0x91, 0x95, 0xE4, 0x79,
        0xE7, 0xC8, 0x37, 0x6D, 0x8D, 0xD5, 0x4E, 0xA9, 0x6C, 0x56, 0xF4, 0xEA, 0x65, 0x7A, 0xAE, 0x08,
        0xBA, 0x78, 0x25, 0x2E, 0x1C, 0xA6, 0xB4, 0xC6, 0xE8, 0xDD, 0x74, 0x1F, 0x4B, 0xBD, 0x8B, 0x8A,
        0x70, 0x3E, 0xB5, 0x66, 0x48, 0x03, 0xF6, 0x0E, 0x61, 0x35, 0x57, 0xB9, 0x86, 0xC1, 0x1D, 0x9E,
        0xE1, 0xF8, 0x98, 0x11, 0x69, 0xD9, 0x8E, 0x94, 0x9B, 0x1E, 0x87, 0xE9, 0xCE, 0x55, 0x28, 0xDF,
        0x8C, 0xA1, 0x89, 0x0D, 0xBF, 0xE6, 0x42, 0x68, 0x41, 0x99, 0x2D, 0x0F, 0xB0, 0x54, 0xBB, 0x16,
    ]
)

_inverse = bytearray(256)
for _index, _value in enumerate(SBOX):
    _inverse[_value] = _index
INV_SBOX = bytes(_inverse)

RCON = (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36)


def _xtime(value: int) -> int:
    value <<= 1
    if value & 0x100:
        value ^= 0x11B
    return value & 0xFF


def _bytes_to_matrix(data: bytes) -> list[list[int]]:
    return [list(data[offset : offset + 4]) for offset in range(0, 16, 4)]


def _matrix_to_bytes(matrix: list[list[int]]) -> bytes:
    return bytes(byte for row in matrix for byte in row)


def _add_round_key(state: list[list[int]], round_key: list[list[int]]) -> None:
    for column in range(4):
        for row in range(4):
            state[column][row] ^= round_key[column][row]


def _sub_bytes(state: list[list[int]]) -> None:
    for column in range(4):
        for row in range(4):
            state[column][row] = SBOX[state[column][row]]


def _inv_sub_bytes(state: list[list[int]]) -> None:
    for column in range(4):
        for row in range(4):
            state[column][row] = INV_SBOX[state[column][row]]


def _shift_rows(state: list[list[int]]) -> None:
    for row in range(1, 4):
        values = [state[column][row] for column in range(4)]
        for column in range(4):
            state[column][row] = values[(column + row) % 4]


def _inv_shift_rows(state: list[list[int]]) -> None:
    for row in range(1, 4):
        values = [state[column][row] for column in range(4)]
        for column in range(4):
            state[column][row] = values[(column - row) % 4]


def _mix_column(column: list[int]) -> None:
    total = column[0] ^ column[1] ^ column[2] ^ column[3]
    first = column[0]
    column[0] ^= total ^ _xtime(column[0] ^ column[1])
    column[1] ^= total ^ _xtime(column[1] ^ column[2])
    column[2] ^= total ^ _xtime(column[2] ^ column[3])
    column[3] ^= total ^ _xtime(column[3] ^ first)


def _mix_columns(state: list[list[int]]) -> None:
    for column in state:
        _mix_column(column)


def _inv_mix_columns(state: list[list[int]]) -> None:
    for column in state:
        u = _xtime(_xtime(column[0] ^ column[2]))
        v = _xtime(_xtime(column[1] ^ column[3]))
        column[0] ^= u
        column[1] ^= v
        column[2] ^= u
        column[3] ^= v
    _mix_columns(state)


def _expand_key(key: bytes) -> list[list[list[int]]]:
    words = _bytes_to_matrix(key)
    round_index = 1
    while len(words) < 44:
        word = list(words[-1])
        if len(words) % 4 == 0:
            word = word[1:] + word[:1]
            word = [SBOX[byte] for byte in word]
            word[0] ^= RCON[round_index - 1]
            round_index += 1
        word = [left ^ right for left, right in zip(word, words[-4])]
        words.append(word)
    return [words[offset : offset + 4] for offset in range(0, 44, 4)]


class AES128:
    """AES with a 16-byte key."""

    block_size = 16

    def __init__(self, key: bytes):
        if len(key) != 16:
            raise ValueError("AES-128 needs a 16-byte key")
        self._round_keys = _expand_key(bytes(key))

    def encrypt_block(self, block: bytes) -> bytes:
        if len(block) != 16:
            raise ValueError("AES block must be 16 bytes")
        state = _bytes_to_matrix(block)
        _add_round_key(state, self._round_keys[0])
        for round_index in range(1, 10):
            _sub_bytes(state)
            _shift_rows(state)
            _mix_columns(state)
            _add_round_key(state, self._round_keys[round_index])
        _sub_bytes(state)
        _shift_rows(state)
        _add_round_key(state, self._round_keys[10])
        return _matrix_to_bytes(state)

    def decrypt_block(self, block: bytes) -> bytes:
        if len(block) != 16:
            raise ValueError("AES block must be 16 bytes")
        state = _bytes_to_matrix(block)
        _add_round_key(state, self._round_keys[10])
        for round_index in range(9, 0, -1):
            _inv_shift_rows(state)
            _inv_sub_bytes(state)
            _add_round_key(state, self._round_keys[round_index])
            _inv_mix_columns(state)
        _inv_shift_rows(state)
        _inv_sub_bytes(state)
        _add_round_key(state, self._round_keys[0])
        return _matrix_to_bytes(state)

    def encrypt_cbc(self, plaintext: bytes, iv: bytes) -> bytes:
        if len(iv) != 16:
            raise ValueError("IV must be 16 bytes")
        padded = pad(plaintext)
        previous = iv
        output = bytearray()
        for offset in range(0, len(padded), 16):
            block = bytes(left ^ right for left, right in zip(padded[offset : offset + 16], previous))
            previous = self.encrypt_block(block)
            output.extend(previous)
        return bytes(output)

    def decrypt_cbc(self, ciphertext: bytes, iv: bytes) -> bytes:
        if len(iv) != 16:
            raise ValueError("IV must be 16 bytes")
        if not ciphertext or len(ciphertext) % 16:
            raise ValueError("ciphertext length must be a multiple of 16")
        previous = iv
        output = bytearray()
        for offset in range(0, len(ciphertext), 16):
            block = ciphertext[offset : offset + 16]
            decrypted = self.decrypt_block(block)
            output.extend(left ^ right for left, right in zip(decrypted, previous))
            previous = block
        return unpad(bytes(output))


def pad(data: bytes) -> bytes:
    padding = 16 - (len(data) % 16)
    return data + bytes([padding]) * padding


def unpad(data: bytes) -> bytes:
    if not data or len(data) % 16:
        raise ValueError("invalid padded data")
    padding = data[-1]
    if not 1 <= padding <= 16 or data[-padding:] != bytes([padding]) * padding:
        raise ValueError("invalid PKCS#7 padding")
    return data[:-padding]
