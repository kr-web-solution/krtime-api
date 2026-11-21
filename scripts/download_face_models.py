#!/usr/bin/env python3
"""Download licence-cleared YuNet + SFace weights from OpenCV Zoo (with SHA256)."""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "app" / "ml" / "weights"

MODELS = [
    {
        "name": "YuNet face detection",
        "file": "face_detection_yunet_2023mar.onnx",
        "url": (
            "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/"
            "models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
        ),
        "sha256": "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
        "licence": "MIT (OpenCV Zoo / YuNet directory)",
    },
    {
        "name": "SFace recognition",
        "file": "face_recognition_sface_2021dec.onnx",
        "url": (
            "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/"
            "models/face_recognition_sface/face_recognition_sface_2021dec.onnx"
        ),
        "sha256": "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
        "licence": "Apache-2.0 (OpenCV Zoo / SFace directory)",
    },
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"Weights directory: {OUT}")
    for model in MODELS:
        dest = OUT / model["file"]
        if dest.is_file() and sha256_file(dest) == model["sha256"]:
            print(f"OK  {model['name']} (cached, verified) — {model['licence']}")
            continue
        print(f"GET {model['name']} …")
        req = urllib.request.Request(model["url"], headers={"User-Agent": "AttendGuard/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp, dest.open("wb") as out:
            out.write(resp.read())
        digest = sha256_file(dest)
        if digest != model["sha256"]:
            dest.unlink(missing_ok=True)
            print(f"FAIL checksum for {model['file']}: got {digest}", file=sys.stderr)
            return 1
        print(f"OK  {model['name']} downloaded — {model['licence']}")
    print(
        "\nMiniFASNet-class weights are NOT downloaded: confirm weight licence before bundling.\n"
        "Server uses a documented basic quality/spoof proxy until then."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
