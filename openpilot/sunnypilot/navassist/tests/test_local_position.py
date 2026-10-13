import math

from openpilot.cereal import log
from openpilot.sunnypilot.navassist.navassistd import local_position_std_m


def test_local_position_reads_capnp_list_without_slicing():
  location = log.LiveLocationKalman.new_message()
  location.positionECEF.valid = True
  location.positionECEF.std = [3.0, 4.0, 0.0]
  assert local_position_std_m(location.as_reader()) == 5.0


def test_invalid_local_position_is_rejected():
  location = log.LiveLocationKalman.new_message()
  location.positionECEF.valid = True
  location.positionECEF.std = [3.0, 4.0]
  assert math.isinf(local_position_std_m(location.as_reader()))
