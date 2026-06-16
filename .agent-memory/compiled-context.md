# Agent Task Brief

## Goal
h??y s???a firmware esp32 ????? bi???n tool PC streaming th??nh tool search v?? ph??t video youtube nh?? t??i m?? t???

## Current State
- h??y s???a firmware esp32 ????? bi???n tool PC streaming th??nh tool search v?? ph??t video youtube nh?? t??i m?? t???
- Claude latest response: Done. Build passed (exit 0) and the merged firmware is at `built-firmware\xiaozhi-es3c28p-current-merged.bin`.

## Summary

The PC-streaming tool is now a YouTube search-and-play tool, end to end:

1. **LLM** calls `self.youtube.search_and_play(query)`.
2. **Firmware** reads the proxy URL+token from NVS, calls `proxy/search`, downloads + decodes 5 thumbnails, and shows a tappable portrait list (thumbnail + title).
3. **User taps** a row ??? firmware sets `proxy/control?source=<url>` then streams that video as RGB332 + synced PCM (same engine/quality as PC stream). Long-press dismisses the list.
4. **Proxy URL + token** are configured on the ClockHome web page (port 80), stored in NVS.

Both edited files compiled (`clock_home.cc.obj`, `freenove-...lcd.cc.obj` in the build log).

## Not done yet
- **Not flashed.** Want me to flash it? `.\up_firmware.bat` (COM3 @ 460800 default, or `-Port COMx`).
- **Not on-device verified.** Worth checking after flashing: that Vietnamese titles render in `font_vi_16`, the 5-row touch hit-boxes line up, and the ~25s synchronous yt-dlp search doesn't trip an MCP-call timeout (if it does, I'd move the search to a PSRAM worker task).
- You'll need to **d
...[truncated]
- Claude latest response: I've loaded Monitor but the build is already running as a background task that will notify me on completion ??? no need to double-watch. Let me summarize while it finishes.

## What I changed

**Firmware ??? `freenove-esp32s3-display-2.8-lcd.cc`** (the PC-streaming tool is now a YouTube search-and-play tool):
- Replaced the `self.video.play_pc_stream` MCP tool with **`self.youtube.search_and_play(query)`**. The LLM calls it with a search term.
- `YoutubeSearchAndShow()` ??? reads the proxy URL+token from NVS, calls `proxy/search?q=...`, parses the JSON (cJSON), downloads + JPEG-decodes up to **5 thumbnails**, and builds a portrait, tappable list overlay (thumbnail + title per row, Vietnamese font `font_vi_16`).
- Touch dispatch: a **tap on a row** plays that video, a **long-press dismisses** the list (added before the clock early-return so it's modal).
- `PlayYoutubeSelection()` ??? `GET proxy/control?source=<url>` then `StartRgb332Stream(base, token)`.
- Refactored `StartPcStream` ??? shared `StartRgb332Stream(base_url, token, fps)`, so the same RGB332+PCM engine now drives the cloud proxy (token appended as `?token=[REDACTED] The LAN PC-stream button path is unchanged.

**Firmware ??? `
...[truncated]
- Claude prompt: b??? PC-stream boot test ??i
- Claude prompt: <task-notification>
<task-id>b2hctrztm</task-id>
<tool-use-id>toolu_01SG9eNsrzvFHNYTuS883gnq</tool-use-id>
<output-file>C:\Users\rkaka\AppData\Local\Temp\claude\D--TAILIEU-MyProject-firmware-esp-xiaozhi-ai\48ac6804-209f-4246-9d01-5643d44d6b90\tasks\b2hctrztm.output</output-file>
<status>completed</status>
<summary>Background command "cd "D:\TAILIEU\MyProject\firmware esp\xiaozhi ai"; .\build_firmware.bat 2&gt;&amp;1 | Select-Object -Last 60" completed (exit code 0)</summary>
</task-notification>

## Relevant Files
- None recorded.

## Constraints
- None recorded.

## Known Decisions
- None recorded.

## Next Actions
1. Inspect the relevant files before editing.
2. Run focused tests.

## Risks / Do Not Touch
- None recorded.

## Expected Output
- Minimal diff.
- Test result summary.
- Updated handoff note.
