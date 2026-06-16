#!/usr/bin/env python3
"""Cloud YouTube -> RGB332/RGB565 + PCM proxy for the ESP32 TFT.

This mirrors the quality of tools/pc_mjpeg_stream_server.py (320x180 raw
frames at 12 fps + synced 16 kHz mono PCM) but runs on a VPS and takes its
source from a YouTube URL. Intended flow:

  1. LLM/firmware calls  GET /search?q=...        -> JSON list (title+thumbnail)
  2. User taps a video, firmware calls /control?source=<youtube_url>
  3. ESP32 reads  GET /stream.rgb332  and  GET /audio.pcm  (current source)

Both /stream.* and /audio.pcm also accept a per-request ?url= override.
"""
import html
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


DEFAULT_FPS = int(os.environ.get("DEFAULT_FPS", "10"))
DEFAULT_WIDTH = int(os.environ.get("DEFAULT_WIDTH", "320"))
DEFAULT_QUALITY = int(os.environ.get("DEFAULT_QUALITY", "16"))
PROXY_TOKEN = os.environ.get("PROXY_TOKEN", "")
YTDLP_BIN = os.environ.get("YTDLP_BIN", "yt-dlp")
FFMPEG_BIN = os.environ.get("FFMPEG_BIN", "ffmpeg")
SEARCH_RESULTS = int(os.environ.get("SEARCH_RESULTS", "8"))

# Must match the firmware (kRgb332Width/kRgb332Height in the board file).
FRAME_HEIGHT = 180


class SharedState:
    """Single current source shared by the paired video + audio requests.

    The firmware opens /stream.rgb332 and /audio.pcm as two separate HTTP
    requests, so the audio handler seeks to the video session's current
    position (video_started_at) to stay in sync, exactly like the PC server.
    """

    def __init__(self, fps, width, quality):
        self.lock = threading.Lock()
        self.source = ""
        self.fps = fps
        self.width = width
        self.quality = quality
        self.video_started_at = None

    def snapshot(self):
        with self.lock:
            return self.source, self.fps, self.width, self.quality

    def update(self, source=None, fps=None, width=None, quality=None):
        with self.lock:
            if source is not None:
                self.source = source
            if fps is not None:
                self.fps = fps
            if width is not None:
                self.width = width
            if quality is not None:
                self.quality = quality

    def mark_video_started(self):
        with self.lock:
            self.video_started_at = time.monotonic()

    def clear_video_started(self):
        with self.lock:
            self.video_started_at = None

    def video_position(self):
        with self.lock:
            if self.video_started_at is None:
                return None
            return time.monotonic() - self.video_started_at


class CloudYoutubeProxyHandler(BaseHTTPRequestHandler):
    server_version = "CloudYoutubeProxy/1.0"

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if parsed.path == "/health":
            self._send_text("ok\n")
            return

        if parsed.path in ("/", "/control"):
            if not self._authorized(params):
                self.send_error(401, "Missing or invalid token")
                return
            self._handle_control(params)
            return

        if parsed.path == "/search":
            if not self._authorized(params):
                self.send_error(401, "Missing or invalid token")
                return
            self._handle_search(params)
            return

        if parsed.path == "/stream.rgb332":
            self._handle_raw_stream(params, "rgb8", "rgb332", bytes_per_pixel=1)
            return

        if parsed.path == "/stream.rgb565":
            self._handle_raw_stream(params, "rgb565be", "rgb565be", bytes_per_pixel=2)
            return

        if parsed.path == "/stream.mjpg":
            self._handle_mjpeg_stream(params)
            return

        if parsed.path == "/audio.pcm":
            self._handle_audio(params)
            return

        self.send_error(404)

    # ---- source selection -------------------------------------------------

    def _select_source(self, params):
        """Resolve the source for this request: ?url= override else shared."""
        override = params.get("url", [params.get("source", [""])[0]])[0].strip()
        if override:
            self.server.state.update(source=override)
            return override
        source, _, _, _ = self.server.state.snapshot()
        return source

    def _handle_control(self, params):
        source = params.get("source", [params.get("url", [None])[0]])[0]
        fps = self._int_param(params, "fps", None, 1, 15)
        width = self._int_param(params, "width", None, 160, 320)
        quality = self._int_param(params, "quality", None, 2, 31)
        if source is not None:
            self.server.state.update(source=source.strip(), fps=fps, width=width, quality=quality)
            self.server.state.clear_video_started()

        current_source, current_fps, current_width, current_quality = self.server.state.snapshot()
        host = self.headers.get("Host", "")
        token = params.get("token", [PROXY_TOKEN])[0]
        tq = f"?token={urllib.parse.quote(token)}" if token else ""

        body = f"""<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ESP32 Cloud YouTube Proxy</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 760px; margin: 32px auto; padding: 0 16px; line-height: 1.45; }}
    input {{ width: 100%; box-sizing: border-box; padding: 10px; margin: 6px 0 14px; }}
    button {{ padding: 10px 14px; }}
    code {{ word-break: break-all; }}
  </style>
</head>
<body>
  <h1>ESP32 Cloud YouTube Proxy</h1>
  <form method="get" action="/control">
    <label>YouTube URL (or search query via /search)</label>
    <input name="source" value="{html.escape(current_source)}" placeholder="https://www.youtube.com/watch?v=...">
    <label>Token</label>
    <input name="token" value="{html.escape(token)}" placeholder="required if PROXY_TOKEN is set">
    <label>FPS</label>
    <input name="fps" value="{current_fps}">
    <label>Width</label>
    <input name="width" value="{current_width}">
    <label>JPEG quality (lower is better, MJPEG only)</label>
    <input name="quality" value="{current_quality}">
    <button type="submit">Set current source</button>
  </form>
  <p>Same-quality endpoints as the PC stream server (320x{FRAME_HEIGHT}):</p>
  <p>RGB332 video: <code>http://{html.escape(host)}/stream.rgb332{tq}</code></p>
  <p>RGB565 video: <code>http://{html.escape(host)}/stream.rgb565{tq}</code></p>
  <p>PCM audio (16 kHz mono): <code>http://{html.escape(host)}/audio.pcm{tq}</code></p>
  <p>Search (JSON): <code>http://{html.escape(host)}/search?q=QUERY{('&token=' + html.escape(token)) if token else ''}</code></p>
  <p>Current source: <code>{html.escape(current_source or "(none)")}</code></p>
</body>
</html>
"""
        self._send_html(body)

    def _handle_search(self, params):
        query = params.get("q", [params.get("query", [""])[0]])[0].strip()
        if not query:
            self.send_error(400, "Missing q")
            return
        count = self._int_param(params, "n", SEARCH_RESULTS, 1, 20)
        try:
            result = subprocess.run(
                [YTDLP_BIN, f"ytsearch{count}:{query}",
                 "--flat-playlist", "--dump-json", "--no-warnings", "--force-ipv4"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
        except subprocess.CalledProcessError as exc:
            sys.stderr.write(exc.stderr.decode(errors="ignore") if exc.stderr else str(exc))
            self.send_error(502, "yt-dlp search failed")
            return
        except subprocess.TimeoutExpired:
            self.send_error(504, "yt-dlp search timed out")
            return

        videos = []
        for line in result.stdout.decode(errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            vid = entry.get("id")
            if not vid:
                continue
            videos.append({
                "id": vid,
                "title": entry.get("title", ""),
                # Always a canonical watch URL: --flat-playlist may set "url" to a
                # bare video id, which /control?source= cannot resolve.
                "url": f"https://www.youtube.com/watch?v={vid}",
                "thumbnail": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
                "duration": entry.get("duration"),
                "uploader": entry.get("uploader") or entry.get("channel", ""),
            })

        self._send_json({"query": query, "results": videos})

    # ---- streaming --------------------------------------------------------

    def _handle_raw_stream(self, params, pix_fmt, frame_format_header, bytes_per_pixel):
        if not self._authorized(params):
            self.send_error(401, "Missing or invalid token")
            return
        source = self._select_source(params)
        if not source:
            self.send_error(409, "No source set; call /control?source=YOUTUBE_URL first")
            return
        _, fps, width, _ = self.server.state.snapshot()

        try:
            media_url = self._resolve_youtube_url(source, audio=False)
        except subprocess.CalledProcessError as exc:
            sys.stderr.write(exc.stderr.decode(errors="ignore") if exc.stderr else str(exc))
            self.send_error(502, "yt-dlp failed")
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Frame-Format", frame_format_header)
        self.send_header("X-Frame-Width", str(width))
        self.send_header("X-Frame-Height", str(FRAME_HEIGHT))
        self.send_header("X-Frame-Fps", str(fps))
        self.end_headers()

        ffmpeg_cmd = [
            FFMPEG_BIN, "-hide_banner", "-loglevel", "error",
            "-re", "-i", media_url,
            "-an",
            "-vf", (f"fps={fps},scale={width}:{FRAME_HEIGHT}:force_original_aspect_ratio=decrease:"
                    f"flags=lanczos,pad={width}:{FRAME_HEIGHT}:(ow-iw)/2:(oh-ih)/2,format={pix_fmt}"),
            "-pix_fmt", pix_fmt,
            "-f", "rawvideo", "pipe:1",
        ]

        process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.server.state.mark_video_started()
        frame_size = width * FRAME_HEIGHT * bytes_per_pixel
        frame_count = 0
        skipped = 0
        frame_period = 1.0 / max(1, fps)
        send_debt = 0.0
        self._tune_stream_socket()
        print(f"{frame_format_header} client {self.client_address[0]} connected: "
              f"source={source!r}, fps={fps}, frame_size={frame_size}")
        try:
            while True:
                frame = self._read_exact(process.stdout, frame_size)
                if frame is None:
                    break
                frame_count += 1
                # Drop frames only on sustained backpressure so queued late
                # frames don't arrive in bursts and stutter on the ESP32.
                if send_debt > frame_period:
                    send_debt -= frame_period
                    skipped += 1
                    continue
                send_start = time.monotonic()
                self.wfile.write(frame)
                self.wfile.flush()
                send_debt += (time.monotonic() - send_start) - frame_period
                if send_debt < 0.0:
                    send_debt = 0.0
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self._reap(process, frame_format_header)
            self.server.state.clear_video_started()
            print(f"{frame_format_header} client {self.client_address[0]} disconnected "
                  f"after {frame_count} frame(s), skipped {skipped}")

    def _handle_mjpeg_stream(self, params):
        if not self._authorized(params):
            self.send_error(401, "Missing or invalid token")
            return
        source = self._select_source(params)
        if not source:
            self.send_error(409, "No source set; call /control?source=YOUTUBE_URL first")
            return
        _, fps, width, quality = self.server.state.snapshot()

        try:
            media_url = self._resolve_youtube_url(source, audio=False)
        except subprocess.CalledProcessError as exc:
            sys.stderr.write(exc.stderr.decode(errors="ignore") if exc.stderr else str(exc))
            self.send_error(502, "yt-dlp failed")
            return

        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        ffmpeg_cmd = [
            FFMPEG_BIN, "-hide_banner", "-loglevel", "error",
            "-re", "-i", media_url,
            "-an",
            "-vf", (f"fps={fps},scale={width}:{FRAME_HEIGHT}:force_original_aspect_ratio=decrease:"
                    f"flags=lanczos,pad={width}:{FRAME_HEIGHT}:(ow-iw)/2:(oh-ih)/2,format=yuvj420p"),
            "-c:v", "mjpeg", "-q:v", str(quality),
            "-f", "mpjpeg", "-boundary", "frame", "pipe:1",
        ]
        process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            while True:
                chunk = process.stdout.read(4096)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self._reap(process, "mjpeg")

    def _handle_audio(self, params):
        if not self._authorized(params):
            self.send_error(401, "Missing or invalid token")
            return
        source = self._select_source(params)
        if not source:
            self.send_error(409, "No source set; call /control?source=YOUTUBE_URL first")
            return

        try:
            media_url = self._resolve_youtube_url(source, audio=True)
        except subprocess.CalledProcessError as exc:
            sys.stderr.write(exc.stderr.decode(errors="ignore") if exc.stderr else str(exc))
            self.send_error(502, "yt-dlp failed")
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        # Seek to the video session's current position so audio enabled (or
        # re-enabled) mid-stream starts in sync instead of from the beginning.
        seek_args = []
        position = self.server.state.video_position()
        if position is not None and position > 1.0:
            seek_args = ["-ss", f"{position:.2f}"]
            print(f"Audio client seeking to video position {position:.2f}s")

        ffmpeg_cmd = [
            FFMPEG_BIN, "-hide_banner", "-loglevel", "error",
            "-re", *seek_args, "-i", media_url,
            "-vn", "-ac", "1", "-ar", "16000",
            "-f", "s16le", "pipe:1",
        ]
        process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        try:
            while True:
                chunk = process.stdout.read(4096)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self._reap(process, "audio")

    # ---- helpers ----------------------------------------------------------

    def _resolve_youtube_url(self, source, audio):
        if "youtube.com/" not in source and "youtu.be/" not in source:
            # Already a direct media URL or file path.
            return source
        # Smallest available rendition: the proxy downscales to 320x180 anyway,
        # so the lowest-quality source minimises VPS download + ffmpeg CPU.
        if audio:
            fmt = "worstaudio/worst"
        else:
            fmt = "worstvideo/worst"
        result = subprocess.run(
            [YTDLP_BIN, "--no-playlist", "--force-ipv4", "-g", "-f", fmt, source],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        )
        urls = [line.strip() for line in result.stdout.decode().splitlines() if line.strip()]
        if not urls:
            raise subprocess.CalledProcessError(1, "yt-dlp", stderr=b"No media URL returned")
        return urls[0]

    @staticmethod
    def _read_exact(stream, size):
        """Read exactly size bytes; return None on EOF/short read."""
        buf = bytearray()
        while len(buf) < size:
            chunk = stream.read(size - len(buf))
            if not chunk:
                return None
            buf.extend(chunk)
        return bytes(buf)

    def _reap(self, process, tag):
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
        if process.returncode not in (0, None):
            sys.stderr.write(f"ffmpeg {tag} exited with code {process.returncode}\n")

    def _tune_stream_socket(self):
        try:
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 128 * 1024)
        except OSError:
            pass

    def _authorized(self, params):
        if not PROXY_TOKEN:
            return True
        token = params.get("token", [""])[0] or self.headers.get("X-Proxy-Token", "")
        return token == PROXY_TOKEN

    @staticmethod
    def _int_param(params, name, default, minimum, maximum):
        if name not in params:
            return default
        try:
            value = int(params[name][0])
        except (ValueError, IndexError):
            return default
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

    def _send_json(self, obj):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


class CloudYoutubeProxyServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address, handler, state):
        super().__init__(server_address, handler)
        self.state = state


def main():
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8088"))
    state = SharedState(DEFAULT_FPS, DEFAULT_WIDTH, DEFAULT_QUALITY)
    server = CloudYoutubeProxyServer((host, port), CloudYoutubeProxyHandler, state)
    print(f"Serving on http://{host}:{port}")
    print(f"  control page : http://{host}:{port}/control")
    print(f"  search (JSON): http://{host}:{port}/search?q=QUERY")
    print(f"  RGB332 video : http://{host}:{port}/stream.rgb332")
    print(f"  RGB565 video : http://{host}:{port}/stream.rgb565")
    print(f"  PCM audio    : http://{host}:{port}/audio.pcm")
    print(f"Frame: {DEFAULT_WIDTH}x{FRAME_HEIGHT} @ {DEFAULT_FPS} fps. Requires yt-dlp and ffmpeg.")
    if PROXY_TOKEN:
        print("PROXY_TOKEN is enabled.")
    server.serve_forever()


if __name__ == "__main__":
    main()
