import torch
import torch.nn as nn
import torch.nn.functional as F

from .conversions import transform_points


__all__ = [
    "HomographyWarper",
    "homography_warp",
]


def create_meshgrid(height, width, normalized_coordinates=True):
    '''Generates a coordinate grid for an image of width(cols), height(rows).
    This is normalized to be in the range [-1,1] to be consistent with the
    pytorch function grid_sample.
    http://pytorch.org/docs/master/nn.html#torch.nn.functional.grid_sample
    Returns a 3xN matrix.
    '''
    if normalized_coordinates:
        xs = torch.linspace(-1, 1, width)
        ys = torch.linspace(-1, 1, height)
    else:
        xs = torch.linspace(0, width - 1, width)
        ys = torch.linspace(0, height - 1, height)
    return torch.stack(torch.meshgrid([ys, xs])).view(1, 2, -1)[:, (1, 0), :]


# layer api

class HomographyWarper(nn.Module):
    """Warps patches by homographies.

    .. math::

        X_{dst} = H_{dst}^{src} * X_{src}

    Args:
        width (int): The width of the image to warp.
        height (int): The height of the image to warp.
        points (Tensor): Tensor[3, N] of homogeneous points in normalized image
                       space [-1, 1] to sample. Optional parameter.
    """

    def __init__(self, height, width, points=None):
        super(HomographyWarper, self).__init__()
        if points is not None:
            assert points.size(0) == 3, "Points must be 3xN"
            self.width = points.size(1)
            self.height = 1
            self.grid = points
        else:
            self.width = width
            self.height = height
            # create base grid to use for computing the flow
            grid = create_meshgrid(height, width, normalized_coordinates=True)
            self.grid = grid.permute(0, 2, 1)  # 1x(H*W)x2

    def warp_grid(self, H):
        """
        :param H: Homography or homographies (stacked) to transform all points
                  in the grid.
        :returns: Tensor[1, Height, Width, 2] containing transformed points in
                  normalized images space.
        """
        batch_size = H.shape[0]  # expand grid to match the input batch size
        grid = self.grid.expand(batch_size, *self.grid.shape[-2:])  # Nx(H*W)x2
        # perform the actual grid transformation,
        # the grid is copied to input device and casted to the same type
        flow = transform_points(H, grid.to(H.device).type_as(H))    # Nx(H*W)x2
        return flow.view(batch_size, self.height, self.width, 2)    # NxHxWx2

    def random_warp(self, patch, dist):
        return self(patch, random_homography(dist))

    def crop_and_warp(self, H, image, roi, padding_mode='zeros'):
        grid = self.warp_grid(H)
        assert len(image.shape) == 4, image.shape

        width, height = image.shape[3], image.shape[2]

        start_x, end_x = roi[2], roi[3] - 1  # inclusive [x_0, x_1]
        start_y, end_y = roi[0], roi[1] - 1

        start_x = (2 * start_x) / width - 1
        end_x = (2 * end_x) / width - 1

        start_y = (2 * start_y) / height - 1
        end_y = (2 * end_y) / height - 1

        b_x = (start_x + end_x) / 2
        a_x = b_x - start_x

        b_y = (start_y + end_y) / 2
        a_y = b_y - start_y
        a = Variable(torch.FloatTensor((a_x, a_y)))
        b = Variable(torch.FloatTensor((b_x, b_y)))
        if grid.is_cuda:
            a = a.cuda()
            b = b.cuda()
        grid = grid * a + b
        return F.grid_sample(
            image, grid, mode='bilinear', padding_mode=padding_mode)

    def forward(self, patch, dst_homo_src, padding_mode='zeros'):
        """Warps an image or tensor from source into reference frame.

        Args:
            patch (Tensor): The image or tensor to warp. Should be from source.
            dst_homo_src (Tensor): The homography or stack of homographies
                                   from source to destination.
            padding_mode (string): Either 'zeros' to replace out of bounds with
                                   zeros or 'border' to choose the closest
                                   border data.

        Return:
            Tensor: Patch sampled at locations from source to destination.

        Shape:
            - Input: :math:`(N, C, H, W)` and :math:`(N, 3, 3)`
            - Output: :math:`(N, C, H, W)`

        Example:
            >>> input = torch.rand(1, 3, 32, 32)
            >>> homography = torch.eye(3).view(1, 3, 3)
            >>> warper = tgm.HomographyWarper(32, 32)
            >>> output = warper(input, homography)  # NxCxHxW
        """
        if not dst_homo_src.device == patch.device:
            raise TypeError("Patch and homography must be on the same device. \
                            Got patch.device: {} dst_H_src.device: {}."
                            .format(patch.device, dst_homo_src.device))
        return F.grid_sample(patch, self.warp_grid(dst_homo_src), 'bilinear',
                             padding_mode=padding_mode)

# functional api


def homography_warp(patch, dst_H_src, dsize, points=None,
                    padding_mode='zeros'):
    """
    .. note:: Functional API for :class:`torgeometry.HomographyWarper`

    Warps patches by homographies.

    Args:
        patch (Tensor): The image or tensor to warp. Should be from source.
        dst_homo_src (Tensor): The homography or stack of homographies from
                               source to destination.
        dsize (tuple): The height and width of the image to warp.
        points (Tensor): Tensor[3, N] of homogeneous points in normalized image
                   space [-1, 1] to sample. Optional parameter.
        padding_mode (string): Either 'zeros' to replace out of bounds with
                               zeros or 'border' to choose the closest border
                               data.

    Return:
        Tensor: Patch sampled at locations from source to destination.

    Shape:
        - Input: :math:`(N, C, H, W)` and :math:`(N, 3, 3)`
        - Output: :math:`(N, C, H, W)`

    Example:
        >>> input = torch.rand(1, 3, 32, 32)
        >>> homography = torch.eye(3).view(1, 3, 3)
        >>> output = tgm.homography_warp(input, homography, (32, 32))  # NxCxHxW
    """
    height, width = dsize
    warper = HomographyWarper(height, width, points)
    return warper(patch, dst_H_src, padding_mode)
