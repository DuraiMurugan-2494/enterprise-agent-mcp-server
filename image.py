"""
MCP Connector — local image OCR and intent analysis.

This connector reads image files from local disk, extracts text when
possible, and returns a best-effort intent label when no text is present.
It uses RapidOCR for OCR and Pillow for lightweight image analysis.
"""

import argparse
import asyncio
import os
import re
import shutil
import threading
import tempfile
from functools import lru_cache
from pathlib import Path

from env_config import load_project_env
from mcp.server.fastmcp import FastMCP
from PIL import Image, ImageFilter, ImageOps, ImageStat, UnidentifiedImageError

load_project_env(Path(__file__).resolve().parent / ".env")

mcp = FastMCP(
    name="image-connector",
    instructions=(
        "Analyze local image files. Returns OCR text when available and "
        "a best-effort intent label for the image when no text is present."
    ),
)

FILES_ROOT_DIR = os.environ.get("FILES_ROOT_DIR", "").strip()
_OCR_LOCK = threading.Lock()


def _resolve(path: str) -> Path:
    p = Path(path)
    if not p.is_absolute() and FILES_ROOT_DIR:
        p = Path(FILES_ROOT_DIR) / p
    return p


def _ocr_text_from_image(path: Path) -> dict:
    try:
        from rapidocr import RapidOCR
    except Exception as exc:
        return {
            "backend": "rapidocr",
            "available": False,
            "warning": f"RapidOCR is not installed or could not be imported: {exc}",
            "text": "",
            "blocks": [],
        }

    try:
        engine = _get_ocr_engine(RapidOCR)
        with _OCR_LOCK:
            result = engine(str(path))
    except Exception as exc:
        return {
            "backend": "rapidocr",
            "available": False,
            "warning": f"OCR failed: {exc}",
            "text": "",
            "blocks": [],
        }

    blocks = []
    try:
        blocks = result.to_json() or []
    except Exception:
        blocks = []

    if not blocks:
        boxes = getattr(result, "boxes", None)
        txts = getattr(result, "txts", None) or []
        scores = getattr(result, "scores", None) or []
        if boxes is not None and txts and scores:
            for box, txt, score in zip(boxes, txts, scores):
                if not str(txt).strip():
                    continue
                blocks.append(
                    {
                        "box": box.tolist() if hasattr(box, "tolist") else box,
                        "txt": str(txt),
                        "score": float(score),
                    }
                )

    text_parts = [str(block.get("txt", "")).strip() for block in blocks if block.get("txt")]
    text = "\n".join(part for part in text_parts if part).strip()

    return {
        "backend": "rapidocr",
        "available": True,
        "warning": None,
        "text": text,
        "blocks": blocks,
    }


@lru_cache(maxsize=1)
def _get_ocr_engine(rapidocr_factory):
    # OCR model initialization is expensive; cache one engine per process.
    return rapidocr_factory()


def _image_stats(image: Image.Image) -> dict:
    grayscale = ImageOps.grayscale(image)
    stats = ImageStat.Stat(grayscale)
    edge_stats = ImageStat.Stat(grayscale.filter(ImageFilter.FIND_EDGES))
    width, height = image.size
    return {
        "width": width,
        "height": height,
        "aspect_ratio": round((width / height) if height else 0.0, 4),
        "mean": round(stats.mean[0], 2),
        "stddev": round(stats.stddev[0], 2),
        "edge_mean": round(edge_stats.mean[0], 2),
    }


def _classify_intent(image: Image.Image, ocr_text: str) -> dict:
    normalized = ocr_text.lower().strip()
    if normalized:
        categories = [
            (
                "resume/document",
                ("objective", "experience", "education", "skills", "project", "summary", "declaration", "resume", "curriculum vitae"),
                "OCR text contains resume or document keywords.",
            ),
            (
                "invoice/receipt",
                ("invoice", "receipt", "subtotal", "amount due", "tax", "gst", "total", "bill"),
                "OCR text contains billing keywords.",
            ),
            (
                "form/profile",
                ("name", "address", "phone", "email", "signature", "date of birth", "dob"),
                "OCR text looks like a form or profile sheet.",
            ),
            (
                "ui/screenshot",
                ("login", "password", "dashboard", "settings", "button", "submit", "search", "error", "menu"),
                "OCR text looks like an application screen or screenshot.",
            ),
            (
                "presentation/slide",
                ("slide", "agenda", "overview", "chart", "table", "bullet"),
                "OCR text looks like a presentation slide.",
            ),
        ]

        scored_matches = []
        for label, keywords, reason in categories:
            matches = [keyword for keyword in keywords if keyword in normalized]
            if matches:
                scored_matches.append((label, len(matches), matches, reason))

        if scored_matches:
            label, match_count, matches, reason = max(scored_matches, key=lambda item: item[1])
            confidence = min(0.98, 0.68 + 0.08 * match_count)
            return {
                "label": label,
                "confidence": round(confidence, 2),
                "reason": f"{reason} Matched: {', '.join(matches[:4])}.",
                "signals": {"matched_keywords": matches[:10], "text_length": len(normalized)},
            }

        word_count = len(re.findall(r"\w+", normalized))
        if word_count >= 40:
            return {
                "label": "text_document",
                "confidence": 0.7,
                "reason": "OCR found a large amount of text but no stronger category match.",
                "signals": {"word_count": word_count, "text_length": len(normalized)},
            }

        return {
            "label": "text_snippet",
            "confidence": 0.56,
            "reason": "OCR found text, but there were not enough clues to specialize further.",
            "signals": {"word_count": word_count, "text_length": len(normalized)},
        }

    stats = _image_stats(image)
    if stats["stddev"] < 8 and stats["edge_mean"] < 8:
        label = "blank_or_flat_image"
        confidence = 0.94
        reason = "The image has very low contrast and edge density."
    elif stats["edge_mean"] > 25 and 0.75 <= stats["aspect_ratio"] <= 2.2:
        label = "screenshot_or_slide"
        confidence = 0.74
        reason = "The image has strong edges and a screen-like aspect ratio."
    elif stats["stddev"] > 38 and stats["edge_mean"] < 20:
        label = "photo"
        confidence = 0.7
        reason = "The image has substantial tonal variation without strong text-like edges."
    else:
        label = "diagram_or_graphic"
        confidence = 0.62
        reason = "No readable text was found; the image looks more like a graphic or diagram."

    return {
        "label": label,
        "confidence": confidence,
        "reason": reason,
        "signals": stats,
    }


@mcp.tool()
async def image_analyze(path: str) -> dict:
    """Analyze a local image. Returns OCR text plus a best-effort intent label."""

    def _run():
        image_path = _resolve(path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image file not found: {image_path}")

        with tempfile.TemporaryDirectory() as temp_dir:
            image_copy = Path(temp_dir) / image_path.name
            shutil.copy2(image_path, image_copy)

            try:
                with Image.open(image_copy) as raw_image:
                    image = ImageOps.exif_transpose(raw_image).convert("RGB")
                    image_info = {
                        "format": raw_image.format,
                        "mode": raw_image.mode,
                        "size": list(image.size),
                    }
            except UnidentifiedImageError as exc:
                raise ValueError(f"Unsupported image file: {image_path}") from exc

            ocr = _ocr_text_from_image(image_copy)
            intent = _classify_intent(image, ocr.get("text", ""))

            ocr_text = ocr.get("text", "") or ""
            text_lines = [line for line in ocr_text.splitlines() if line.strip()]

            return {
                "path": str(image_path),
                "image": image_info,
                "ocr": {
                    "backend": ocr.get("backend"),
                    "available": ocr.get("available", False),
                    "warning": ocr.get("warning"),
                    "text": ocr_text,
                    "line_count": len(text_lines),
                    "blocks": ocr.get("blocks", []),
                },
                "intent": intent,
                "summary": (
                    f"OCR text extracted and intent classified as {intent['label']}."
                    if ocr_text
                    else f"No readable text found; intent classified as {intent['label']}."
                ),
            }

    return await asyncio.to_thread(_run)


def main():
    parser = argparse.ArgumentParser(description="Image OCR and intent connector")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if not args.serve:
        print("Run with --serve to expose the MCP tools.")
        return

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        print(f"Serving MCP over HTTP at http://{args.host}:{args.port}/mcp (Ctrl+C to stop)")
        mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()