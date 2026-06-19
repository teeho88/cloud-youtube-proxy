# Hướng dẫn cập nhật / redeploy proxy trên VPS

Proxy `cloud-youtube-proxy` chạy bằng Docker trên GCP e2-micro. Tài liệu này mô tả
cách đẩy thay đổi code lên và triển khai lại container.

## Thông tin VPS (cố định)

| Mục | Giá trị |
|---|---|
| Project | `esp32-proxy-499610` |
| Instance | `instance-esp32` |
| Zone | `us-west1-b` |
| IP | `34.169.58.148` |
| Container | `esp32-youtube-proxy` (port `8088`) |
| Repo trên VPS | `/home/vluongthanh98/cloud-youtube-proxy` (chủ sở hữu: `vluongthanh98`) |
| User login SSH | `rkaka` (≠ chủ repo → git phải chạy bằng `sudo -u vluongthanh98`) |
| GitHub | `https://github.com/teeho88/cloud-youtube-proxy` (nhánh `main`) |
| `PROXY_TOKEN` | dài 32 ký tự, lấy lại tự động từ container đang chạy (xem `gg_E2_micro.key`) |

## Cách nhanh nhất (từ máy Windows)

Từ thư mục gốc workspace:

```bat
REM 1. Sửa code trong tools\cloud-youtube-proxy\app.py rồi commit
cd tools\cloud-youtube-proxy
git add app.py
git commit -m "proxy: <mô tả>"
git push origin main
cd ..\..

REM 2. Redeploy trên VPS (1 lệnh)
.\redeploy_proxy.bat
```

Hoặc gộp bước push + redeploy:

```bat
.\redeploy_proxy.bat -Push
```

`redeploy_proxy.bat` gọi `tools\redeploy_vps_proxy.ps1` → SSH vào VPS → `git pull` →
chạy `redeploy.sh`.

## redeploy.sh làm gì (chạy trên VPS)

`tools/cloud-youtube-proxy/redeploy.sh` được commit cùng repo nên luôn có sẵn trên VPS
sau lần `git pull` đầu tiên. Nó:

1. `git pull --ff-only` (chạy bằng `sudo -u vluongthanh98` để tránh lỗi *dubious ownership*).
2. Lấy lại `PROXY_TOKEN` từ container đang chạy bằng `docker inspect` (không cần nhập token).
3. `docker build` lại image.
4. `docker rm -f` + `docker run -d --restart unless-stopped -p 8088:8088 -e PROXY_TOKEN=...`.
5. Chờ `/health` trả `ok` (tối đa 30s), in trạng thái container và in các dòng
   `readrate` / `DEFAULT_FPS` / `DEFAULT_QUALITY` để **xác nhận thay đổi đã vào image**.

## Làm thủ công (nếu script lỗi)

SSH vào rồi chạy trực tiếp:

```bash
# Trên máy Windows (PowerShell):
& "$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" compute ssh instance-esp32 --zone=us-west1-b --project=esp32-proxy-499610

# Sau khi vào VPS:
sudo bash /home/vluongthanh98/cloud-youtube-proxy/redeploy.sh
```

## Lưu ý quan trọng

- **fps / quality KHÔNG đổi bằng redeploy.** Proxy nhận `fps`/`quality` thực tế từ
  firmware gửi qua `/control` (lấy từ NVS). `DEFAULT_FPS/QUALITY` trong code chỉ là dự
  phòng. Muốn đổi fps/quality thực tế → vào **trang ClockHome web config** trên thiết bị.
- Các giá trị chỉ nằm trong proxy (vd `-readrate`) thì redeploy là có hiệu lực ngay.
- Trên Windows, gọi gcloud bằng **PowerShell**; trong `--command` **không dùng dấu nháy kép**
  (gcloud trên Windows phân tích sai). Lệnh phức tạp nên đóng gói bằng base64:
  `echo <base64> | base64 -d | sudo bash`.
- Lần SSH đầu sẽ hỏi host-key của PuTTY → script tự `echo "y"` để chấp nhận.
- `docker` cần `sudo` (user `rkaka` không thuộc group docker).
