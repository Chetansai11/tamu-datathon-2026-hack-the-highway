"""Turn a folder of PDFs into page-level JSONL for document classification or RAG.

    python toolkit/doc_extract.py docs/ --out outputs/pages.jsonl

Records text, image count and whether the page needs OCR or vision (little text but an
image present: scans, stamps, forms). Pages flagged needs_ocr hold content a text-only
pipeline silently misses, so those are the ones to send to OCR or a vision model.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pymupdf


def extract(path: Path) -> list[dict]:
    rows = []
    with pymupdf.open(path) as doc:
        for i, page in enumerate(doc):
            text = page.get_text("text").strip()
            images = len(page.get_images(full=True))
            rows.append({
                "file": path.name, "page": i + 1, "pages_total": doc.page_count,
                "text": text, "chars": len(text), "images": images,
                "needs_ocr": len(text) < 40 and images > 0,
            })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--out", default="outputs/pages.jsonl")
    args = ap.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    root = Path(args.folder)
    files = sorted(root.rglob("*.pdf")) if root.is_dir() else [root]
    total = ocr = failed = 0
    with out.open("w", encoding="utf-8") as f:
        for p in files:
            try:
                rows = extract(p)
            except Exception as e:  # corrupt or encrypted file: report it, keep going
                failed += 1
                print(f"FAILED {p.name}: {e}")
                continue
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
                total += 1
                ocr += r["needs_ocr"]
    print(f"{len(files) - failed}/{len(files)} files, {total} pages, {ocr} need OCR/vision -> {out}")


if __name__ == "__main__":
    main()
