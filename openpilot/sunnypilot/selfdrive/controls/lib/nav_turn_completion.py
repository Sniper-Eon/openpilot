import math


TURN_GEOMETRY_LAT_ACCEL_MPS2 = 1.1


def sp_turn_geometry_active(controls_state, speed_mps: float) -> bool:
  """Return whether SP's current desired path is still in a substantial turn."""
  curvature = float(controls_state.desiredCurvature)
  lateral_accel = max(0.0, float(speed_mps)) ** 2 * abs(curvature)
  return math.isfinite(lateral_accel) and lateral_accel >= TURN_GEOMETRY_LAT_ACCEL_MPS2
