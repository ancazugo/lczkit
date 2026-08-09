"""The bundled server: does it answer Range requests, and answer them correctly?

**This is the test that would have caught the design error.** `http.server.SimpleHTTPRequestHandler`
does not implement `Range` at all — it answers 200 with the whole body every time — and PMTiles is
built entirely on ranged reads of one large file. A site served by the stdlib handler unmodified
would re-download a 60 MB tileset for every tile, which is indistinguishable from "slow" until
someone measures it.

Nothing here touches the network beyond a loopback socket, so it runs in CI with no `DATA_DIR`.
"""

from __future__ import annotations

import http.client
import threading
from collections.abc import Iterator
from http import HTTPStatus
from pathlib import Path

import pytest

from lczkit.viz.serve import RangeRequestHandler, _parse_range, _Server

BODY = bytes(range(256)) * 64  # 16 KiB, every byte value, so an off-by-one is visible


@pytest.fixture
def server(tmp_path: Path) -> Iterator[tuple[str, int]]:
    (tmp_path / "tiles").mkdir()
    (tmp_path / "tiles" / "units.pmtiles").write_bytes(BODY)
    (tmp_path / "index.html").write_text("<!doctype html><title>t</title>", encoding="utf-8")

    class Handler(RangeRequestHandler):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, directory=str(tmp_path), **kwargs)  # type: ignore[arg-type]

        def log_message(self, *args: object) -> None:
            """Silence the per-request stderr line; pytest captures it as noise, not signal."""

    instance = _Server(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield "127.0.0.1", instance.server_address[1]
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(timeout=5)


def request(
    server: tuple[str, int], path: str, headers: dict[str, str] | None = None
) -> http.client.HTTPResponse:
    connection = http.client.HTTPConnection(*server, timeout=10)
    connection.request("GET", path, headers=headers or {})
    return connection.getresponse()


def test_a_ranged_read_returns_206_and_exactly_the_bytes_asked_for(
    server: tuple[str, int],
) -> None:
    response = request(server, "/tiles/units.pmtiles", {"Range": "bytes=100-199"})

    assert response.status == HTTPStatus.PARTIAL_CONTENT
    assert response.getheader("Content-Range") == f"bytes 100-199/{len(BODY)}"
    assert response.getheader("Content-Length") == "100"
    assert response.read() == BODY[100:200]


def test_an_open_ended_range_runs_to_the_end_of_the_file(server: tuple[str, int]) -> None:
    response = request(server, "/tiles/units.pmtiles", {"Range": "bytes=16000-"})

    assert response.status == HTTPStatus.PARTIAL_CONTENT
    assert response.read() == BODY[16000:]


def test_a_suffix_range_returns_the_tail(server: tuple[str, int]) -> None:
    """`bytes=-N` asks for the last N bytes. A PMTiles reader may issue one, and a server that
    handles only the common form fails intermittently, which is the worst kind of failure."""
    response = request(server, "/tiles/units.pmtiles", {"Range": "bytes=-64"})

    assert response.status == HTTPStatus.PARTIAL_CONTENT
    assert response.read() == BODY[-64:]
    assert (
        response.getheader("Content-Range") == f"bytes {len(BODY) - 64}-{len(BODY) - 1}/{len(BODY)}"
    )


def test_a_range_past_the_end_is_refused_with_the_size(server: tuple[str, int]) -> None:
    response = request(server, "/tiles/units.pmtiles", {"Range": f"bytes={len(BODY) + 10}-"})

    assert response.status == HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE
    assert response.getheader("Content-Range") == f"bytes */{len(BODY)}"


def test_an_unranged_request_still_returns_the_whole_file(server: tuple[str, int]) -> None:
    response = request(server, "/tiles/units.pmtiles")

    assert response.status == HTTPStatus.OK
    assert response.read() == BODY


def test_range_support_is_advertised_so_a_client_will_use_it(server: tuple[str, int]) -> None:
    """pmtiles.js checks `Accept-Ranges` before issuing a ranged read. A server that supports
    ranges but does not say so is treated as one that does not."""
    response = request(server, "/index.html")
    response.read()

    assert response.getheader("Accept-Ranges") == "bytes"


def test_pmtiles_is_served_as_binary(server: tuple[str, int]) -> None:
    """Served as text, a tileset arrives re-encoded and the reader fails on the header magic."""
    response = request(server, "/tiles/units.pmtiles", {"Range": "bytes=0-7"})
    response.read()

    assert response.getheader("Content-Type") == "application/octet-stream"


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("bytes=0-99", (0, 99)),
        ("bytes=500-", (500, None)),
        ("bytes=-500", (-500, None)),
        ("bytes=0-0", (0, 0)),
        ("bytes=0-9,20-29", (None, None)),
        ("items=0-9", (None, None)),
        ("bytes=abc", (None, None)),
        ("bytes=", (None, None)),
    ],
)
def test_range_parsing(header: str, expected: tuple[int | None, int | None]) -> None:
    assert _parse_range(header) == expected
