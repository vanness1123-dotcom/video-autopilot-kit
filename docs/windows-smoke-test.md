# Windows Smoke Test

This document describes the minimum Windows smoke test for this repository.
It verifies that Python, FFmpeg, FFprobe, and the runnable examples are working
before using the larger CapCut-assisted workflow.

## Prerequisites

- Python 3.9+
- FFmpeg and FFprobe available on `PATH`
- Windows PowerShell configured for UTF-8 output in the current session

Recommended PowerShell session setup:

```powershell
$env:PYTHONIOENCODING="utf-8"
chcp 65001
```

## Verification Commands

Run these commands from the repository root:

```powershell
git status --short
python --version
ffmpeg -version
ffprobe -version
python examples/02_caption_broll_match.py
python examples/01_vertical_short.py
```

## Common Errors

### `UnicodeEncodeError: cp950`

On Traditional Chinese Windows environments, redirected or non-UTF-8 terminal
output may use the `cp950` code page. The examples print Unicode arrows and
symbols, so Python may fail while printing even though the program logic is
otherwise working.

Typical symptom:

```text
UnicodeEncodeError: 'cp950' codec can't encode character
```

Fix it for the current PowerShell session:

```powershell
$env:PYTHONIOENCODING="utf-8"
chcp 65001
```

### `FileNotFoundError: ffmpeg not found`

`examples/01_vertical_short.py` launches `ffmpeg` and `ffprobe` through Python
subprocesses. If FFmpeg is not installed or its `bin` directory is not on
`PATH`, the script fails before generating media.

Typical symptom:

```text
FileNotFoundError: [WinError 2] The system cannot find the file specified
```

Fix:

1. Install FFmpeg.
2. Add the FFmpeg `bin` directory to Windows `PATH`, for example:

```text
C:\Tools\ffmpeg\bin
```

3. Open a new PowerShell session and verify:

```powershell
ffmpeg -version
ffprobe -version
```

## Success Criteria

The smoke test passes when all of the following are true:

- `examples/02_caption_broll_match.py` completes successfully and prints the
  auto-sequencer plan.
- `examples/01_vertical_short.py` completes successfully and prints the output
  path for `short.mp4`.
- The generated `short.mp4` is a 1080x1920 vertical video.
- `ffprobe` output for the generated file shows both a video stream and an
  audio stream.

Expected final `ffprobe` signal from `examples/01_vertical_short.py`:

```text
codec_type=video
width=1080
height=1920
codec_type=audio
```
