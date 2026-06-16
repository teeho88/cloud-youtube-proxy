#!/usr/bin/env python3
import html
import os
import subprocess
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


DEFAULT_FPS = int(os.environ.get("DEFAULT_FPS", "5"))
DEFAULT_WIDTH = int(os.environ.get("DEFAULT_WIDTH", "240"))
DEFAULT_QUALITY = int(os.environ.get("DEFAULT_QUALITY", "8"))
PROXY_TOKEN = os.environ.get("PROXY_TOKEN", "")


class CloudYoutubeProxyHandler(BaseHTTPRequestHandler):
    server_version = "CloudYoutubeMjpegProxy/0.1"

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if parsed.path == "/health":
            self._send_text("ok\n")
            return

        if parsed.path == "/":
            self._send_home(params)
            return

        if parsed.path != "/stream":
            self.send_error(404)
            return

        if not self._authorized(params):
            self.send_error(401, "Missing or invalid token")
            return

        youtube_url = params.get("url", [""])[0]
        fps = self._int_param(params, "fps", DEFAULT_FPS, 1, 15)
        width = self._int_param(params, "width", DEFAULT_WIDTH, 120, 320)
        quality = self._int_param(params, "quality", DEFAULT_QUALITY, 2, 31)

        if not youtube_url:
            self.send_error(400, "Missing url")
            return

        try:
            media_url = self._resolve_youtube_url(youtube_url)
        except subprocess.CalledProcessError as exc:
            self.send_error(502, "yt-dlp failed")
            sys.stderr.write(exc.stderr.decode(errors="ignore") if exc.stderr else str(exc))
            return

        ffmpeg_cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-i",
            media_url,
            "-an",
            "-vf",
            f"fps={fps},scale={width}:-2:flags=lanczos",
            "-q:v",
            str(quality),
            "-f",
            "mpjpeg",
            "-boundary",
            "frame",
            "pipe:1",
        ]

        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            while True:
                chunk = process.stdout.read(4096)
                if not chunk:
                    break
                self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()

    def _resolve_youtube_url(self, youtube_url):
        format_selector = "bestvideo[height<=360][ext=mp4]/bestvideo[height<=360]/best[height<=360]/best"
        result = subprocess.run(
            ["yt-dlp", "--no-playlist", "--force-ipv4", "-g", "-f", format_selector, youtube_url],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        urls = [line.strip() for line in result.stdout.decode().splitlines() if line.strip()]
        if not urls:
            raise subprocess.CalledProcessError(1, "yt-dlp", stderr=b"No media URL returned")
        return urls[0]

    def _send_home(self, params):
        youtube_url = params.get("url", [""])[0]
        fps = self._int_param(params, "fps", DEFAULT_FPS, 1, 15)
        width = self._int_param(params, "width", DEFAULT_WIDTH, 120, 320)
        quality = self._int_param(params, "quality", DEFAULT_QUALITY, 2, 31)
        token = params.get("token", [PROXY_TOKEN])[0]

        stream_url = ""
        if youtube_url:
            query = {
                "url": youtube_url,
                "fps": str(fps),
                "width": str(width),
                "quality": str(quality),
            }
            if token:
                query["token"] = token
            host = self.headers.get("Host", "")
            scheme = "https" if self.headers.get("X-Forwarded-Proto") == "https" else "http"
            stream_url = f"{scheme}://{host}/stream?{urllib.parse.urlencode(query)}"

        body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ESP32 YouTube MJPEG Proxy</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 760px; margin: 32px auto; padding: 0 16px; line-height: 1.45; }}
    input {{ width: 100%; box-sizing: border-box; padding: 10px; margin: 6px 0 14px; }}
    button {{ padding: 10px 14px; }}
    code, textarea {{ width: 100%; box-sizing: border-box; }}
    textarea {{ min-height: 90px; padding: 10px; }}
  </style>
</head>
<body>
  <h1>ESP32 YouTube MJPEG Proxy</h1>
  <form method="get" action="/">
    <label>YouTube URL</label>
    <input name="url" value="{html.escape(youtube_url)}" placeholder="https://www.youtube.com/watch?v=...">
    <label>Token</label>
    <input name="token" value="{html.escape(token)}" placeholder="required if PROXY_TOKEN is set">
    <label>FPS</label>
    <input name="fps" value="{fps}">
    <label>Width</label>
    <input name="width" value="{width}">
    <label>JPEG quality, lower is better quality</label>
    <input name="quality" value="{quality}">
    <button type="submit">Create ESP32 stream URL</button>
  </form>
  <h2>ESP32 URL</h2>
  <textarea readonly>{html.escape(stream_url)}</textarea>
  <p>Use this URL with firmware tool <code>self.video.play_stream</code>.</p>
</body>
</html>
"""
        self._send_html(body)

    def _authorized(self, params):
        if not PROXY_TOKEN:
            return True
        token = params.get("token", [""])[0] or self.headers.get("X-Proxy-Token", "")
        return token == PROXY_TOKEN

    @staticmethod
    def _int_param(params, name, default, minimum, maximum):
        try:
            value = int(params.get(name, [str(default)])[0])
        except ValueError:
            value = default
        return max(minimum, min(maximum, value))

    def _send_text(self, body):
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, body):
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def main():
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8088"))
    server = ThreadingHTTPServer((host, port), CloudYoutubeProxyHandler)
    print(f"Serving on http://{host}:{port}")
    print("Requires yt-dlp and ffmpeg.")
    if PROXY_TOKEN:
        print("PROXY_TOKEN is enabled.")
    server.serve_forever()


if __name__ == "__main__":
    main()
