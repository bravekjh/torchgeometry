import unittest

import torch
import torchgeometry as dgm


class Tester(unittest.TestCase):

    def test_convert_points_to_homogeneous(self):
        points = torch.rand(1, 2, 3)

        points_h = dgm.convert_points_to_homogeneous(points)
        assert (points_h[..., -1] == torch.ones(1, 2, 1)).all()

    def test_convert_points_from_homogeneous(self):
        points_h = torch.rand(1, 2, 3)
        points_h[..., -1] = 1.0

        points = dgm.convert_points_from_homogeneous(points_h)
        assert (points_h[..., :2] == points[..., :2]).all()


if __name__ == '__main__':
    unittest.main()
