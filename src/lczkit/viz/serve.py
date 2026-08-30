"""A standard-library static server that answers HTTP Range requests.

    python serve.py [--port 8000] [--directory .]

**This file is copied verbatim into every site directory**, which is why it imports nothing outside
the standard library and takes no arguments the site does not already know. A reader who receives
the directory years from now needs a Python interpreter and nothing else.

**Why it exists at all.** PMTiles works by asking for byte ranges of one file over HTTP, and
`http.server.SimpleHTTPRequestHandler` does not implement `Range` — it answers 200 with the whole
body, every time, for every tile. A 60 MB tileset would then be re-sent for each of hundreds of tile
reads. So the forty lines below are the difference between a site that loads and one that does not,
and they are cheaper than taking on a web-server dependency for them.

**Why a server is needed rather than opening `index.html` directly.** The Fetch standard leaves
`file:` URLs unhandled, so `fetch()` against one returns a network error in both Chrome and Firefox,
and PMTiles is built on `fetch`. Nothing here reaches the network: the server is local, the assets
are vendored, and the map has no basemap API key and no CDN link. "Offline" is satisfied; "no
process at all" is not achievable with range-requested tiles in a current browser.
"""

from __future__ import annotations

import argparse
import os
import socketserver
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from typing import IO

CHUNK = 1 << 16


class RangeRequestHandler(SimpleHTTPRequestHandler):
    """`SimpleHTTPRequestHandler` plus single-range `bytes=` support and the right MIME types."""

    _remaining: int | None = None
    """Bytes still owed on the current partial response, set by `send_head` and consumed by
    `copyfile`. The two are separate calls in the base class, and the byte count is the only state
    that has to survive between them."""

    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".pmtiles": "application/octet-stream",
        ".json": "application/json",
        ".mjs": "text/javascript",
    }

    def end_headers(self) -> None:
        """Advertise range support on every response, then close the header block."""
        # Advertised unconditionally: pmtiles.js checks for it before issuing a ranged read, and a
        # server that supports ranges but does not say so is treated as one that does not.
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def send_head(self) -> IO[bytes] | None:  # type: ignore[override]
        """Answer a `Range` request with `206 Partial Content`, or defer to the base class.

        This is the whole reason the site ships its own server. `SimpleHTTPRequestHandler` has
        no range support, so it would re-send an entire tileset per tile — and PMTiles reads a
        map by issuing one ranged read per tile.

        A request with no `Range` header, or for a directory, goes to the base class untouched.
        A start past the end of the file gets `416` with a `Content-Range` stating the real size,
        which is what lets a client that guessed wrong recover. Sets `_remaining` for `copyfile`.
        """
        header = self.headers.get("Range")
        if header is None:
            return super().send_head()

        start, end = _parse_range(header)
        if start is None:
            self.send_error(HTTPStatus.BAD_REQUEST, "malformed Range header")
            return None

        path = Path(self.translate_path(self.path))
        if path.is_dir():
            return super().send_head()
        try:
            handle = path.open("rb")
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND, "file not found")
            return None

        size = path.stat().st_size
        if start < 0:
            start, end = max(0, size + start), None
        if start >= size:
            handle.close()
            self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return None

        last = size - 1 if end is None else min(end, size - 1)
        handle.seek(start)
        self.send_response(HTTPStatus.PARTIAL_CONTENT)
        self.send_header("Content-Type", self.guess_type(str(path)))
        self.send_header("Content-Range", f"bytes {start}-{last}/{size}")
        self.send_header("Content-Length", str(last - start + 1))
        self.end_headers()
        self._remaining = last - start + 1
        return handle

    def copyfile(self, source: IO[bytes], outputfile: IO[bytes]) -> None:  # type: ignore[override]
        """Write exactly the bytes `send_head` promised, or the whole file if it promised none.

        `_remaining` is cleared before the loop rather than after, so a connection that drops
        part-way cannot leave a stale byte count for the next request on the same handler.
        """
        remaining = self._remaining
        if remaining is None:
            super().copyfile(source, outputfile)
            return
        self._remaining = None
        while remaining > 0:
            block = source.read(min(CHUNK, remaining))
            if not block:
                break
            outputfile.write(block)
            remaining -= len(block)


def _parse_range(header: str) -> tuple[int | None, int | None]:
    """Parse a single `bytes=` range into `(start, end)`, both inclusive, `end` optional.

    A **negative start is a suffix range** — `bytes=-500` asks for the last 500 bytes — and is
    returned as-is because resolving it needs the file size, which is the caller's to know. Suffix
    ranges are handled rather than rejected because a PMTiles reader may issue one, and a range
    server that fails only on the less common form fails intermittently, which is worse.

    Multi-range requests return `(None, None)`; nothing here issues one and answering a
    `multipart/byteranges` body badly would be worse than declining it.
    """
    if not header.startswith("bytes=") or "," in header:
        return None, None
    spec = header[len("bytes=") :].strip()
    first, separator, last = spec.partition("-")
    if not separator:
        return None, None
    try:
        if not first:
            return (-int(last), None) if last else (None, None)
        return int(first), int(last) if last else None
    except ValueError:
        return None, None


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(directory: Path, port: int = 8000, *, bind: str = "127.0.0.1") -> None:
    """Serve `directory` until interrupted."""
    os.chdir(directory)
    with _Server((bind, port), RangeRequestHandler) as server:
        bound = server.server_address[1]
        print(f"lczkit site on http://{bind}:{bound}/  (ctrl-c to stop)", flush=True)
        server.serve_forever()


def main() -> None:
    """Command-line entry point: serve the directory this file sits in, over loopback.

    Defaulting `--directory` to the script's own parent is what makes a built site openable by
    `python serve.py` from inside it, with no arguments and nothing installed.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--directory", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    serve(args.directory, args.port, bind=args.bind)


if __name__ == "__main__":
    main()
