#!/usr/bin/env python3
"""
AODD PostToolUse hook — compress Playwright screenshots before they bloat the model context.

How it works
------------
Claude Code's PostToolUse event delivers a JSON blob on stdin that contains the
tool name and the tool response.  When the response carries a base64-encoded
image that is larger than MAX_B64_BYTES, this script:

  1. Decodes the image to a temp file.
  2. Compresses it to ≤ TARGET_WIDTH × TARGET_HEIGHT JPEG at JPEG_QUALITY.
     Tries, in order:
       - sips          (macOS — built-in, no install needed)
       - PowerShell    (Windows — built-in via System.Drawing, no install needed)
       - magick        (Windows ImageMagick v7 CLI)
       - convert       (ImageMagick v6 / Linux)
       - Pillow        (cross-platform, pip install Pillow)
  3. Re-encodes and prints a replacement response JSON to stdout so Claude
     Code substitutes the compressed image for the original.

If no compression tool is available, or the image is already small enough,
the script exits 0 without printing anything (no-op).

Installation
------------
See the README in https://github.com/Koh0920/aodd for full setup instructions.
"""

import base64
import json
import os
import subprocess
import sys
import tempfile

# Tuning parameters — adjust to taste
MAX_B64_BYTES = 400_000   # ~300 KB decoded; images smaller than this are left alone
TARGET_WIDTH  = 1280
TARGET_HEIGHT = 800
JPEG_QUALITY  = 65        # 0–100; 65 gives a good size/quality trade-off


# ---------------------------------------------------------------------------
# Compression back-ends
# ---------------------------------------------------------------------------

def _compress_sips(in_path: str, out_path: str) -> bool:
    """macOS built-in image tool — no extra installs required."""
    r = subprocess.run(
        [
            "sips",
            "-z", str(TARGET_HEIGHT), str(TARGET_WIDTH),
            "-s", "format", "jpeg",
            "-s", "formatOptions", str(JPEG_QUALITY),
            in_path, "--out", out_path,
        ],
        capture_output=True,
    )
    return r.returncode == 0 and os.path.isfile(out_path) and os.path.getsize(out_path) > 0


def _compress_powershell(in_path: str, out_path: str) -> bool:
    """Windows built-in: PowerShell + System.Drawing — no extra installs required."""
    script = (
        "Add-Type -AssemblyName System.Drawing;"
        f"$img=[System.Drawing.Image]::FromFile('{in_path}');"
        f"$tw={TARGET_WIDTH};$th={TARGET_HEIGHT};"
        "$rw=$img.Width;$rh=$img.Height;"
        "if($rw -gt $tw -or $rh -gt $th){"
        "  $scale=[Math]::Min($tw/$rw,$th/$rh);"
        "  $rw=[int]($rw*$scale);$rh=[int]($rh*$scale)"
        "};"
        "$bmp=New-Object System.Drawing.Bitmap($rw,$rh);"
        "$g=[System.Drawing.Graphics]::FromImage($bmp);"
        "$g.InterpolationMode='HighQualityBicubic';"
        "$g.DrawImage($img,0,0,$rw,$rh);"
        "$g.Dispose();$img.Dispose();"
        "$enc=[System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders()|"
        "  Where-Object{$_.MimeType -eq 'image/jpeg'}|Select-Object -First 1;"
        "$params=New-Object System.Drawing.Imaging.EncoderParameters(1);"
        f"$params.Param[0]=New-Object System.Drawing.Imaging.EncoderParameter("
        f"[System.Drawing.Imaging.Encoder]::Quality,{JPEG_QUALITY}L);"
        f"$bmp.Save('{out_path}',$enc,$params);"
        "$bmp.Dispose()"
    )
    r = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
    )
    return r.returncode == 0 and os.path.isfile(out_path) and os.path.getsize(out_path) > 0


def _compress_imagemagick_v7(in_path: str, out_path: str) -> bool:
    """ImageMagick v7 on Windows uses 'magick' instead of 'convert'."""
    r = subprocess.run(
        [
            "magick",
            in_path,
            "-resize", f"{TARGET_WIDTH}x{TARGET_HEIGHT}>",
            "-quality", str(JPEG_QUALITY),
            out_path,
        ],
        capture_output=True,
    )
    return r.returncode == 0 and os.path.isfile(out_path) and os.path.getsize(out_path) > 0


def _compress_imagemagick(in_path: str, out_path: str) -> bool:
    """ImageMagick v6 'convert' — available on Linux and older Windows installs."""
    r = subprocess.run(
        [
            "convert",
            in_path,
            "-resize", f"{TARGET_WIDTH}x{TARGET_HEIGHT}>",
            "-quality", str(JPEG_QUALITY),
            out_path,
        ],
        capture_output=True,
    )
    return r.returncode == 0 and os.path.isfile(out_path) and os.path.getsize(out_path) > 0


def _compress_pillow(in_path: str, out_path: str) -> bool:
    """Pillow (pip install Pillow) — cross-platform fallback."""
    try:
        from PIL import Image  # type: ignore
        img = Image.open(in_path).convert("RGB")
        img.thumbnail((TARGET_WIDTH, TARGET_HEIGHT))
        img.save(out_path, "JPEG", quality=JPEG_QUALITY, optimize=True)
        return os.path.isfile(out_path) and os.path.getsize(out_path) > 0
    except Exception:
        return False


def compress(raw_bytes: bytes) -> bytes | None:
    """Return compressed JPEG bytes, or None if no compressor is available."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(raw_bytes)
        in_path = f.name

    out_path = in_path.replace(".png", "_c.jpg")

    try:
        ok = (
            _compress_sips(in_path, out_path)           # macOS
            or _compress_powershell(in_path, out_path)  # Windows (built-in)
            or _compress_imagemagick_v7(in_path, out_path)  # Windows ImageMagick v7
            or _compress_imagemagick(in_path, out_path) # Linux / ImageMagick v6
            or _compress_pillow(in_path, out_path)      # cross-platform fallback
        )
        if ok:
            with open(out_path, "rb") as f:
                return f.read()
        return None
    finally:
        for p in (in_path, out_path):
            try:
                os.unlink(p)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        return  # not JSON — leave untouched

    tool_name = event.get("tool_name", "")
    if "screenshot" not in tool_name.lower():
        return  # not a screenshot tool — nothing to do

    tool_response = event.get("tool_response", {})

    # The Anthropic tool-result schema wraps content in a list of blocks.
    content = tool_response.get("content", [])
    if not isinstance(content, list):
        return

    modified = False

    for block in content:
        if not isinstance(block, dict) or block.get("type") != "image":
            continue
        source = block.get("source", {})
        if source.get("type") != "base64":
            continue

        b64_data: str = source.get("data", "")
        if not b64_data or len(b64_data) <= MAX_B64_BYTES:
            continue  # already small enough

        raw_bytes = base64.b64decode(b64_data)
        compressed = compress(raw_bytes)
        if compressed is None:
            sys.stderr.write(
                "[aodd] no compression tool found "
                "(tried sips, PowerShell, magick, convert, Pillow)\n"
            )
            continue

        orig_kb = len(raw_bytes) // 1024
        comp_kb = len(compressed) // 1024
        sys.stderr.write(
            f"[aodd] screenshot compressed: {orig_kb} KB → {comp_kb} KB "
            f"(max {TARGET_WIDTH}×{TARGET_HEIGHT} JPEG {JPEG_QUALITY}%)\n"
        )

        source["data"] = base64.b64encode(compressed).decode()
        source["media_type"] = "image/jpeg"
        modified = True

    if modified:
        # Emit the replacement tool response.
        # Claude Code picks this up and substitutes it for the original.
        print(json.dumps({"tool_response": tool_response}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"[aodd] compression hook error: {exc}\n")
        sys.exit(0)  # never block the session on a hook failure
