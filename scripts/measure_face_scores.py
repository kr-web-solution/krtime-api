#!/usr/bin/env python3
"""Measure SFace cosine similarity between pairs of face images.

Usage:
  python scripts/measure_face_scores.py path/to/a.jpg path/to/b.jpg
  python scripts/measure_face_scores.py --dir samples/
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.face_engine import FaceEngine, FaceEngineUnavailable  # noqa: E402


def score_pair(engine: FaceEngine, a: Path, b: Path) -> float:
    da = engine.detect_and_embed(a.read_bytes())
    db = engine.detect_and_embed(b.read_bytes())
    return engine.cosine_similarity(da.embedding, db.embedding)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="*", help="Two image paths, or omit with --dir")
    parser.add_argument("--dir", type=Path, help="Directory of images; score consecutive pairs")
    args = parser.parse_args()

    engine = FaceEngine()
    try:
        engine.ensure_loaded()
    except FaceEngineUnavailable as exc:
        print(exc, file=sys.stderr)
        return 1

    if args.dir:
        files = sorted(
            p for p in args.dir.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
        )
        if len(files) < 2:
            print("Need at least two images in --dir", file=sys.stderr)
            return 1
        for i in range(len(files) - 1):
            s = score_pair(engine, files[i], files[i + 1])
            print(f"{files[i].name} vs {files[i+1].name}: {s:.4f}")
        return 0

    if len(args.images) != 2:
        parser.error("Provide two image paths or --dir")
    a, b = Path(args.images[0]), Path(args.images[1])
    print(f"{a} vs {b}: {score_pair(engine, a, b):.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
