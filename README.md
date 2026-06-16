# Cloud YouTube MJPEG Proxy

Proxy nay chay tren VPS/cloud. ESP32-S3 khong mo YouTube truc tiep; no nhan MJPEG nhe tu proxy.

Luon dat `PROXY_TOKEN` khi dua proxy len internet.

## Chay local bang Docker

```powershell
cd "D:\TAILIEU\MyProject\firmware esp\xiaozhi ai\tools\cloud-youtube-proxy"
docker build -t esp32-youtube-proxy .
docker run --rm -p 8088:8088 -e PROXY_TOKEN=doi-token-nay esp32-youtube-proxy
```

Mo:

```text
http://localhost:8088
```

Paste link YouTube, nhap token, roi copy URL tao ra cho firmware `self.video.play_stream`.

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
  -e DEFAULT_FPS=5 \
  -e DEFAULT_WIDTH=240 \
  esp32-youtube-proxy
```

URL trang tao stream:

```text
http://IP_VPS:8088
```

URL cho ESP32 co dang:

```text
http://IP_VPS:8088/stream?url=YOUTUBE_URL_DA_ENCODE&fps=5&width=240&quality=8&token=doi-token-nay
```

## Cau hinh

- `PORT`: cong HTTP, mac dinh `8088`.
- `PROXY_TOKEN`: khoa bao ve proxy. Nen bat.
- `DEFAULT_FPS`: mac dinh `5`.
- `DEFAULT_WIDTH`: mac dinh `240`.
- `DEFAULT_QUALITY`: mac dinh `8`. Gia tri thap hon la chat luong JPEG cao hon.

## Luu y

- Cloud/VPS can CPU du de ffmpeg transcode realtime.
- ESP32-S3 nen dung `fps=3..8`, `width=160..240`.
- Neu stream bi dung, thu giam `fps`, giam `width`, hoac tang chat luong so `quality` len `10..16`.
- Proxy nay chi nen dung cho thu nghiem ca nhan va cac noi dung ban co quyen truy cap.
