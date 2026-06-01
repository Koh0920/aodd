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
     Tries, in order: sips (macOS), ImageMagick convert, Pillow.
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


def _compress_imagemagick(in_path: str, out_path: str) -> bool:
    """ImageMagick — available on most Linux systems."""
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
            _compress_sips(in_path, out_path)
            or _compress_imagemagick(in_path, out_path)
            or _compress_pillow(in_path, out_path)
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
                "[aodd] no compression tool found (tried sips, convert, Pillow)\n"
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
