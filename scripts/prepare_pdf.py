"""Find candidate map pages and render them; page numbers are one-based."""
import argparse
import json
import re
from pathlib import Path

import pymupdf as fitz


def find_pages(doc):
    terms = re.compile(r"study\s+area|research\s+area|\blocation\b|geograph\w*|研究区|地理位置", re.I)
    results = []
    for i, page in enumerate(doc):
        text = page.get_text(sort=True)
        snippets = [text[max(0, m.start()-100):m.end()+250].replace("\n", " ") for m in terms.finditer(text)]
        if snippets:
            results.append({"page": i+1, "matches": snippets})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--find", action="store_true")
    parser.add_argument("--page", type=int)
    parser.add_argument("--dpi", type=float, default=200)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--crop-pixels", nargs=4, type=int, metavar=("X0", "Y0", "X1", "Y1"))
    args = parser.parse_args()
    with fitz.open(args.pdf) as doc:
        if args.find:
            print(json.dumps(find_pages(doc), ensure_ascii=False, indent=2))
        if args.page is not None:
            if not args.out or not 1 <= args.page <= len(doc) or args.dpi <= 0:
                parser.error("rendering needs --out, positive DPI and a valid one-based --page")
            pix = doc[args.page-1].get_pixmap(dpi=round(args.dpi), alpha=False)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            if args.crop_pixels:
                from PIL import Image
                box = args.crop_pixels
                if not (0 <= box[0] < box[2] <= pix.width and 0 <= box[1] < box[3] <= pix.height):
                    parser.error("crop must lie inside the rendered page")
                Image.frombytes("RGB", (pix.width, pix.height), pix.samples).crop(box).save(args.out)
            else:
                pix.save(args.out)
        elif not args.find:
            parser.error("choose --find or --page")


if __name__ == "__main__":
    main()
