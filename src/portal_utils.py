import math
from numpy import array as np_array, float32 as np_float32, ndarray as np_ndarray


def h_to_i(handle: int) -> int:
    return (handle & 0x7ff) - 1


def angles_to_vec(angles, is_rad: bool = False) -> np_ndarray:
    if not is_rad:
        angles = (math.radians(angles[0]), math.radians(angles[1]), math.radians(angles[2]))
    return np_array((
        math.cos(angles[1])*math.cos(-angles[0]),
        math.sin(angles[1])*math.cos(-angles[0]),
        math.sin(-angles[0])
    ), dtype=np_float32)
