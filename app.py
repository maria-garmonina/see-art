from __future__ import annotations

import json
import os
import hashlib
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from seeart.scraper import BROWSER_USER_AGENT, CACHE_PATH, CONFIG_PATH, ensure_cache, run_scrape

ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ROOT / "static"
ADMIN_TOKEN = os.environ.get("SEEART_ADMIN_TOKEN", "")
IMAGE_CACHE_DIR = ROOT / "data" / "image-cache"
IMAGE_CACHE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
MAX_IMAGE_BYTES = 20_000_000


class SeeArtHandler(SimpleHTTPRequestHandler):
    server_version = "SeeArt/0.1"

    def translate_path(self, path: str) -> str:
        parsed = urlparse(path)
        route = parsed.path
        if route == "/":
            return str(STATIC_ROOT / "index.html")
        if route == "/admin":
            return str(STATIC_ROOT / "admin.html")
        if route.startswith("/static/"):
            return str(ROOT / route.lstrip("/"))
        return str(STATIC_ROOT / route.lstrip("/"))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/exhibitions":
            self.write_json(ensure_cache())
            return
        if parsed.path == "/api/venues":
            self.write_json(read_json(CONFIG_PATH))
            return
        if parsed.path == "/api/image":
            self.write_remote_image(parse_qs(parsed.query).get("url", [""])[0])
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/refresh":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        query = parse_qs(parsed.query)
        token = self.headers.get("X-SeeArt-Token") or query.get("token", [""])[0]
        if not ADMIN_TOKEN:
            self.write_json(
                {"ok": False, "error": "Refresh token is not configured. Set SEEART_ADMIN_TOKEN before starting the server."},
                HTTPStatus.FORBIDDEN,
            )
            return
        if token != ADMIN_TOKEN:
            self.write_json({"ok": False, "error": "Unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return

        try:
            result = run_scrape()
        except Exception as exc:  # Defensive: keep admin refresh from dropping the socket.
            self.write_json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self.write_json({"ok": True, "data": result})

    def write_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def write_remote_image(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid image URL")
            return

        cache_hit = False
        cached = read_cached_image(url)
        if cached:
            content_type, body = cached
            cache_hit = True
        else:
            try:
                content_type, body = fetch_remote_image(url, referer=f"{parsed.scheme}://{parsed.netloc}/")
            except Exception as exc:
                try:
                    content_type, body = fetch_remote_image(url)
                except Exception:
                    self.send_error(HTTPStatus.BAD_GATEWAY, str(exc))
                    return

        if len(body) > MAX_IMAGE_BYTES:
            self.send_error(HTTPStatus.BAD_GATEWAY, "Image is too large")
            return
        if not content_type.lower().startswith(("image/", "application/octet-stream")):
            self.send_error(HTTPStatus.BAD_GATEWAY, "Remote URL did not return an image")
            return
        if not cache_hit:
            write_cached_image(url, content_type, body)

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "public, max-age=86400")
        self.send_header("X-SeeArt-Image-Cache", "hit" if cache_hit else "miss")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def read_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def fetch_remote_image(url: str, referer: str = "") -> tuple[str, bytes]:
    headers = {
        "User-Agent": BROWSER_USER_AGENT,
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    request = Request(url, headers=headers)
    with urlopen(request, timeout=15) as response:
        content_type = response.headers.get("Content-Type", "application/octet-stream")
        body = response.read(MAX_IMAGE_BYTES + 1)
    return content_type, body


def image_cache_paths(url: str) -> tuple[Path, Path]:
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return IMAGE_CACHE_DIR / f"{key}.body", IMAGE_CACHE_DIR / f"{key}.json"


def read_cached_image(url: str) -> tuple[str, bytes] | None:
    body_path, meta_path = image_cache_paths(url)
    if not body_path.exists() or not meta_path.exists():
        return None
    if time.time() - body_path.stat().st_mtime > IMAGE_CACHE_MAX_AGE_SECONDS:
        return None
    try:
        meta = read_json(meta_path)
        content_type = str(meta.get("content_type", "application/octet-stream")) if isinstance(meta, dict) else "application/octet-stream"
        return content_type, body_path.read_bytes()
    except (OSError, json.JSONDecodeError):
        return None


def write_cached_image(url: str, content_type: str, body: bytes) -> None:
    try:
        IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        body_path, meta_path = image_cache_paths(url)
        body_path.write_bytes(body)
        meta_path.write_text(json.dumps({"url": url, "content_type": content_type}), encoding="utf-8")
    except OSError:
        return


def main() -> None:
    host = os.environ.get("SEEART_HOST", "127.0.0.1")
    port = int(os.environ.get("SEEART_PORT", "8000"))
    ensure_cache()
    server = ThreadingHTTPServer((host, port), SeeArtHandler)
    print(f"SeeArt running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
