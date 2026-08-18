from __future__ import annotations

import unittest

try:
    import cv2
    import numpy as np
    from task2_service.ocr import DigitRecognizer
    HAS_OPENCV = True
except ModuleNotFoundError:
    HAS_OPENCV = False


@unittest.skipUnless(HAS_OPENCV, "需先按 requirements.txt 安装OpenCV")
class OcrTests(unittest.TestCase):
    def test_template_fallback_recognizes_supported_digits(self) -> None:
        recognizer = DigitRecognizer({
            "enable_easyocr": False,
            "tesseract_command": "",
            "minimum_confidence": 0.40,
            "template_min_score": 0.30,
        })
        for digit in [1, 2, 3, 4]:
            with self.subTest(digit=digit):
                image = np.full((180, 220, 3), 255, dtype=np.uint8)
                cv2.putText(
                    image, str(digit), (55, 145), cv2.FONT_HERSHEY_SIMPLEX,
                    4.0, (0, 0, 0), 8, cv2.LINE_AA,
                )
                result = recognizer.recognize(image)
                self.assertIsNotNone(result)
                self.assertEqual(result.digit, digit)
