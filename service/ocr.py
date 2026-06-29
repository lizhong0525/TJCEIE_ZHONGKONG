import threading
from typing import Any, Dict

import numpy as np
from PIL import Image


_ocr_engine = None
_ocr_lock = threading.Lock()


def _get_ocr_engine():
    """Lazy-load PaddleOCR as a module-level singleton."""
    global _ocr_engine
    if _ocr_engine is None:
        with _ocr_lock:
            if _ocr_engine is None:
                from paddleocr import PaddleOCR

                _ocr_engine = PaddleOCR(lang="ch", use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False)
    return _ocr_engine


def _is_truthy(value: Any) -> bool:
    """Interpret rule values that may be booleans or strings."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"", "false", "0", "no", "off"}
    return bool(value)


def _fullwidth_to_halfwidth(text: str) -> str:
    """Convert full-width ASCII / digits / punctuation to half-width."""
    out = []
    for ch in text:
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - 0xFF01 + 0x21))
        elif code == 0x3000:
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def _halfwidth_to_fullwidth(text: str) -> str:
    """Convert half-width ASCII / digits / punctuation to full-width."""
    out = []
    for ch in text:
        code = ord(ch)
        if 0x21 <= code <= 0x7E:
            out.append(chr(code - 0x21 + 0xFF01))
        elif code == ord(" "):
            out.append("\u3000")
        else:
            out.append(ch)
    return "".join(out)


def normalize(text: str, rules: Dict[str, Any]) -> str:
    """
    Normalize OCR text according to ``meta.normalize_rules``.

    Supported rules (only truthy rules are applied):

    - ``fullwidth_to_halfwidth`` / ``fullwidth``: full-width ASCII/digits/punctuation
      -> half-width.
    - ``halfwidth_to_fullwidth`` / ``halfwidth``: half-width ASCII/digits/punctuation
      -> full-width.
    - ``case_insensitive``: English characters -> lowercase.
    - ``remove_space``: remove all whitespace characters.
    - default whitespace handling: collapse consecutive whitespace to a single space.
    - ``trim_space``: strip leading/trailing whitespace.
    - ``simplify``: traditional Chinese -> simplified Chinese via ``zhconv`` if
      installed; silently skipped otherwise.
    """
    if not isinstance(text, str):
        text = str(text)
    if not isinstance(rules, dict):
        rules = {}

    if _is_truthy(rules.get("fullwidth_to_halfwidth")) or _is_truthy(
        rules.get("fullwidth")
    ):
        text = _fullwidth_to_halfwidth(text)

    if _is_truthy(rules.get("halfwidth_to_fullwidth")) or _is_truthy(
        rules.get("halfwidth")
    ):
        text = _halfwidth_to_fullwidth(text)

    if _is_truthy(rules.get("case_insensitive")):
        text = text.lower()

    if _is_truthy(rules.get("remove_space")):
        text = "".join(text.split())
    else:
        # Collapse any consecutive whitespace (including full-width spaces already
        # converted above) into a single ordinary space.
        text = " ".join(text.split())

    if _is_truthy(rules.get("trim_space")):
        text = text.strip()

    if _is_truthy(rules.get("simplify")):
        try:
            import zhconv

            text = zhconv.convert(text, "zh-hans")
        except Exception:
            pass

    return text


def _center(box: Any) -> tuple:
    """Compute the center of a four-point box returned by PaddleOCR."""
    pts = [(float(p[0]), float(p[1])) for p in box]
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    return cx, cy


def do_ocr(image: Image.Image, meta: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run PaddleOCR on a PIL image and return normalized text.

    The recognized text boxes are sorted by their center coordinates: top-to-bottom
    then left-to-right.
    """
    engine = _get_ocr_engine()

    img_array = np.array(image.convert("RGB"))
    ocr_result = engine.ocr(img_array)

    lines = []
    if ocr_result and isinstance(ocr_result, list):
        # Single image -> first page, or the result itself.
        page = ocr_result[0] if isinstance(ocr_result[0], list) else ocr_result
        if page:
            for item in page:
                if not item or len(item) < 2:
                    continue
                box, rec = item[0], item[1]
                if not box or not rec:
                    continue
                cx, cy = _center(box)
                text = rec[0] if isinstance(rec, (list, tuple)) else str(rec)
                lines.append((cy, cx, text))

    lines.sort(key=lambda x: (x[0], x[1]))
    raw_text = " ".join(text for _, _, text in lines)

    rules = {}
    if isinstance(meta, dict):
        rules = meta.get("normalize_rules", {}) or {}

    return {"text": normalize(raw_text, rules)}
