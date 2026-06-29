"""Pre-download / cache model weights used by the contest algo gateway.

Run this script after installing dependencies so that the first ``/infer`` call
is not slowed down by network downloads. Missing optional models are reported
but do not crash the script.
"""

import sys
import traceback


def _report(stage: str, ok: bool, exc: Exception | None = None) -> None:
    status = "OK" if ok else "FAIL"
    print(f"[{status}] {stage}")
    if exc is not None:
        print(f"  -> {exc}")
        if "-v" in sys.argv or "--verbose" in sys.argv:
            traceback.print_exception(type(exc), exc, exc.__traceback__)


def _download_classify() -> bool:
    import classify

    classify._load_model()
    # Touch tokenizer + text features so the first inference path is warm.
    if classify._tokenizer is not None:
        _ = classify._tokenizer(classify._english_prompts).to(classify._device)
    return True


def _download_detect_yolo() -> bool:
    import detect

    _ = detect._get_yolo()
    return True


def _download_detect_yolo_world() -> bool:
    import detect

    model = detect._get_yolo_world()
    return model is not None


def _download_ocr() -> bool:
    import ocr

    _ = ocr._get_ocr_engine()
    return True


def main() -> int:
    stages = [
        ("open_clip (classify)", _download_classify, False),
        ("YOLOv8x (detect)", _download_detect_yolo, False),
        ("PaddleOCR (ocr)", _download_ocr, False),
        ("YOLO-World (detect lamp fallback)", _download_detect_yolo_world, True),
    ]

    failed = []
    for name, fn, optional in stages:
        print(f"Downloading {name}...")
        try:
            ok = fn()
            _report(name, ok)
            if not ok and not optional:
                failed.append(name)
        except Exception as exc:  # noqa: BLE001
            _report(name, False, exc)
            if not optional:
                failed.append(name)

    print()
    if failed:
        print("Required stages failed:", ", ".join(failed))
        return 1
    print("All required models cached successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
