"""Frame-protocol tests for atlas.lsp.protocol (C6A LSP wave, subagent E).

Covers: encode/read round-trips over an in-memory asyncio reader, header-block
overrun, missing Content-Length, invalid JSON bodies, truncated bodies, clean
EOF, the four classify_message outcomes, and the error-response envelope.
"""
from __future__ import annotations

import asyncio

import pytest

from atlas.lsp.protocol import (
    ERROR_CONTENT_MODIFIED,
    ERROR_METHOD_NOT_FOUND,
    LSPProtocolError,
    LSPRequestError,
    classify_message,
    encode_message,
    make_error_response,
    make_notification,
    make_request,
    make_response,
    read_message,
)


def _reader(data: bytes) -> asyncio.StreamReader:
    """An asyncio reader pre-loaded with ``data`` and EOF (no real I/O needed)."""
    r = asyncio.StreamReader()
    r.feed_data(data)
    r.feed_eof()
    return r


# ---- encode_message ----------------------------------------------------------

def test_encode_message_header_counts_bytes_not_chars():
    body_text = '{"jsonrpc":"2.0","method":"héllo"}'
    framed = encode_message(make_notification("héllo", None))
    header, _, body = framed.partition(b"\r\n\r\n")
    assert header == f"Content-Length: {len(body)}".encode("ascii")
    assert body.decode("utf-8") == body_text  # compact, non-ASCII kept as UTF-8


def test_encode_message_no_params_key_when_params_none():
    framed = encode_message(make_notification("exit", None))
    assert b'"params"' not in framed


# ---- read_message round-trips ------------------------------------------------

async def test_roundtrip_single_message():
    msg = make_request(3, "initialize", {"rootUri": "file:///x"})
    parsed = await read_message(_reader(encode_message(msg)))
    assert parsed == msg


async def test_roundtrip_multiple_pipelined_messages():
    msgs = [
        make_notification("initialized", {}),
        make_request(0, "shutdown", None),
        make_response(0, None),
        make_notification("textDocument/publishDiagnostics", {"uri": "file:///a", "diagnostics": []}),
    ]
    reader = _reader(b"".join(encode_message(m) for m in msgs))
    parsed = [await read_message(reader) for _ in msgs]
    assert parsed == msgs
    assert await read_message(reader) is None  # clean EOF between messages


async def test_clean_eof_before_any_header_returns_none():
    assert await read_message(_reader(b"")) is None


# ---- framing failures --------------------------------------------------------

async def test_header_block_over_limit_raises():
    # One header line whose padding blows past the 8 KiB cap before the blank line.
    framed = b"Content-Type: " + b"a" * 9000 + b"\r\n\r\n"
    with pytest.raises(LSPProtocolError):
        await read_message(_reader(framed))


async def test_missing_content_length_raises():
    framed = b"Content-Type: application/vscode-jsonrpc\r\n\r\n{}"
    with pytest.raises(LSPProtocolError, match="Content-Length"):
        await read_message(_reader(framed))


async def test_non_integer_content_length_raises():
    framed = b"Content-Length: many\r\n\r\n{}"
    with pytest.raises(LSPProtocolError, match="Content-Length"):
        await read_message(_reader(framed))


async def test_invalid_json_body_raises():
    body = b"{not json"
    framed = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body
    with pytest.raises(LSPProtocolError, match="JSON"):
        await read_message(_reader(framed))


async def test_truncated_body_raises():
    framed = b"Content-Length: 100\r\n\r\nshort"
    with pytest.raises(LSPProtocolError, match="truncated"):
        await read_message(_reader(framed))


async def test_mid_header_eof_raises():
    with pytest.raises(LSPProtocolError):
        await read_message(_reader(b"Content-Length: 2\r\n"))


# ---- classify_message --------------------------------------------------------

def test_classify_request():
    kind, key = classify_message(make_request(7, "initialize", {}))
    assert (kind, key) == ("request", 7)


def test_classify_response_result_and_error():
    kind, key = classify_message(make_response(7, {"capabilities": {}}))
    assert (kind, key) == ("response", 7)
    kind, key = classify_message(make_error_response(7, ERROR_METHOD_NOT_FOUND, "nope"))
    assert (kind, key) == ("response", 7)


def test_classify_notification():
    kind, key = classify_message(make_notification("exit", None))
    assert (kind, key) == ("notification", "exit")


def test_classify_invalid():
    assert classify_message({}) == ("invalid", None)
    assert classify_message({"jsonrpc": "1.0", "id": 1, "method": "x"}) == ("invalid", None)
    assert classify_message({"jsonrpc": "2.0", "id": 1}) == ("invalid", None)  # response without result/error
    assert classify_message({"jsonrpc": "2.0", "result": 1}) == ("invalid", None)  # id-less response
    assert classify_message("not a dict") == ("invalid", None)


# ---- envelopes and error types ----------------------------------------------

def test_make_envelopes_shape():
    assert make_notification("m", {"a": 1}) == {"jsonrpc": "2.0", "method": "m", "params": {"a": 1}}
    assert make_request(1, "m", None) == {"jsonrpc": "2.0", "id": 1, "method": "m"}
    assert make_response("id-1", [1, 2]) == {"jsonrpc": "2.0", "id": "id-1", "result": [1, 2]}


async def test_error_response_envelope_roundtrip():
    err = make_error_response(9, ERROR_METHOD_NOT_FOUND, "method not found: x/y", data={"retry": False})
    assert err["error"] == {"code": -32601, "message": "method not found: x/y", "data": {"retry": False}}
    assert err["id"] == 9
    # survives the framer unchanged
    parsed = await read_message(_reader(encode_message(err)))
    assert parsed == err


def test_error_constants():
    assert ERROR_METHOD_NOT_FOUND == -32601
    assert ERROR_CONTENT_MODIFIED == -32801


def test_lsp_request_error_carries_fields():
    e = LSPRequestError(-32801, "Content modified", {"attempt": 1})
    assert e.code == -32801 and e.message == "Content modified" and e.data == {"attempt": 1}
    assert "Content modified" in str(e)
    assert isinstance(e, Exception) and not isinstance(e, LSPProtocolError)
