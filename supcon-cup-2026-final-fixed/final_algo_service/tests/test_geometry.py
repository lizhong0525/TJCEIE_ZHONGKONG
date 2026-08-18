from __future__ import annotations

import numpy as np
import unittest

from task2_service.geometry import pixel_to_base, rpy_to_matrix, valid_depth_m
from task2_service.models import Pose6D, VisionError


class GeometryTests(unittest.TestCase):
    def test_pixel_to_base_applies_transforms(self) -> None:
        arm = Pose6D(1.0, 2.0, 3.0, 0.0, 0.0, 0.0)
        t_end_camera = np.eye(4)
        t_end_camera[:3, 3] = [0.1, 0.2, 0.3]
        point = pixel_to_base(
            320.0, 240.0, 1.0,
            (500.0, 500.0, 320.0, 240.0),
            rpy_to_matrix(arm), t_end_camera,
        )
        np.testing.assert_allclose(point, [1.1, 2.2, 4.3])

    def test_valid_depth_uses_local_median(self) -> None:
        depth = np.zeros((20, 20), dtype=np.float32)
        depth[8:13, 8:13] = 750.0
        self.assertAlmostEqual(valid_depth_m(depth, 10, 10), 0.75)

    def test_invalid_depth_is_rejected(self) -> None:
        with self.assertRaises(VisionError):
            valid_depth_m(np.zeros((10, 10), dtype=np.float32), 5, 5)
