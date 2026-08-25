import math

from q5_p0450342_solver import head_speed_from_kmax


def test_head_speed_from_kmax():
    assert math.isclose(head_speed_from_kmax(1.6161478322419554), 1.2375105544803762)
