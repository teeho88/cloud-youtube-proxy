# Cloud YouTube Proxy (RGB332 + PCM)

Proxy chay tren VPS/cloud. No convert YouTube -> raw RGB332/RGB565 320x180 @ 12fps
va PCM 16 kHz mono, **giong het chat luong PC stream** (`tools/pc_mjpeg_stream_server.py`).
ESP32-S3 khong mo YouTube truc tiep; no doc raw frame + PCM tu proxy.

Luon dat `PROXY_TOKEN` khi dua proxy len internet.

## Luong su dung

1. LLM/firmware goi `GET /search?q=...` -> JSON danh sach video (title + thumbnail).
2. Nguoi dung chon 1 video -> firmware goi `GET /control?source=<youtube_url>`.
3. ESP32 doc `GET /stream.rgb332` va `GET /audio.pcm` (theo source hien tai).

`/stream.*` va `/audio.pcm` cung nhan `?url=<youtube_url>` de override truc tiep.

## Endpoints

| Path | Mo ta |
|------|-------|
| `GET /search?q=QUERY&n=8` | Tim YouTube, tra JSON `{results:[{id,title,url,thumbnail,duration,uploader}]}` |
| `GET /control?source=URL` | Dat video hien tai (fps/width/quality optional). Khong source -> tra trang test |
| `GET /stream.rgb332` | Raw RGB332 320x180, headers `X-Frame-*` (giong PC server) |
| `GET /stream.rgb565` | Raw RGB565 big-endian 320x180 |
| `GET /stream.mjpg` | MJPEG multipart (fallback/test trinh duyet) |
| `GET /audio.pcm` | PCM s16le mono 16 kHz, seek dong bo voi video |
| `GET /health` | `ok` |

Tat ca (tru `/health`) yeu cau `token=` hoac header `X-Proxy-Token` neu da bat `PROXY_TOKEN`.

## Chay local bang Docker

```powershell
cd "D:\TAILIEU\MyProject\firmware esp\xiaozhi ai\tools\cloud-youtube-proxy"
docker build -t esp32-youtube-proxy .
docker run --rm -p 8088:8088 -e PROXY_TOKEN=doi-token-nay esp32-youtube-proxy
```

Mo `http://localhost:8088/control`, paste link YouTube + token, bam "Set current source".

## Chay tren VPS Linux

```bash
sudo apt update
sudo apt install -y docker.io
git clone <repo-cua-ban>
cd <repo-cua-ban>/tools/cloud-youtube-proxy
sudo docker build -t esp32-youtube-proxy .
sudo docker run -d --restart unless-stopped --name esp32-youtube-proxy \
  -p 8088:8088 \
  -e PROXY_TOKEN=doi-token-nay \
  esp32-youtube-proxy
```

ESP32 URL (mac dinh, khong can query neu da set source qua /control):

```text
http://IP_VPS:8088/stream.rgb332?token=doi-token-nay
http://IP_VPS:8088/audio.pcm?token=doi-token-nay
```

## Cau hinh (env)

- `PORT`: cong HTTP, mac dinh `8088`.
- `PROXY_TOKEN`: khoa bao ve proxy. Nen bat khi public.
- `DEFAULT_FPS`: mac dinh `12` (khop firmware).
- `DEFAULT_WIDTH`: mac dinh `320` (chieu cao co dinh 180).
- `DEFAULT_QUALITY`: chat luong JPEG cho `/stream.mjpg`, mac dinh `16` (thap = dep hon).
- `SEARCH_RESULTS`: so ket qua `/search` mac dinh, mac dinh `8`.

## Luu y

- VPS can CPU du de ffmpeg transcode realtime (320x180@12fps rgb332 + audio 16k la nhe).
- RGB332 ~57.6 KB/frame, 12fps ~5.5 Mbps; can duong truyen VPS->ESP32 du bang thong.
- Discovery UDP (LAN) khong dung cho cloud; firmware phai tro base URL toi IP VPS.
- Proxy nay chi nen dung cho thu nghiem ca nhan va noi dung ban co quyen truy cap.
```
