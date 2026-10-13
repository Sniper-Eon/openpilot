from openpilot.sunnypilot.selfdrive.controls.lib.relative_lane_consistency import RelativeLaneConsistencyFilter


EVENT = ("session-a", 1, 7)


def tracker(*, max_changes=5):
  return RelativeLaneConsistencyFilter(
    presence_stable_ns=500,
    edge_stable_ns=5_000,
    new_lane_stable_ns=3_000,
    cooldown_ns=2_000,
    max_changes=max_changes,
  )


def observe(filter_, now_ns, *, neighbor=True, valid=True, changing=False, steering=False):
  return filter_.update(
    EVENT, direction="left", neighbor_exists=neighbor, observation_valid=valid,
    lane_change_active=changing, steering_pressed=steering, now_ns=now_ns,
  )


def test_neighbor_must_remain_stable_before_relative_lane_change_is_ready():
  consistency = tracker()

  assert not observe(consistency, 0).ready
  assert not observe(consistency, 499).ready
  status = observe(consistency, 500)

  assert status.ready
  assert status.reason == "neighborStable"


def test_invalid_observation_gap_never_counts_toward_stability():
  consistency = tracker()
  observe(consistency, 0)
  assert observe(consistency, 100, valid=False).reason == "observationInvalid"
  assert not observe(consistency, 1_000).ready
  assert not observe(consistency, 1_499).ready
  assert observe(consistency, 1_500).ready


def test_confirmed_edge_requires_longer_stability_before_a_new_lane_rearms():
  consistency = tracker()

  assert not observe(consistency, 0, neighbor=False).edge_confirmed
  assert observe(consistency, 5_000, neighbor=False).edge_confirmed
  assert not observe(consistency, 5_100, neighbor=True).ready
  assert not observe(consistency, 8_099, neighbor=True).ready
  status = observe(consistency, 8_100, neighbor=True)

  assert status.ready
  assert not status.edge_confirmed
  assert status.reason == "newNeighborStable"


def test_lane_change_and_driver_steering_reset_evidence_then_enforce_cooldown():
  consistency = tracker()
  observe(consistency, 0)
  observe(consistency, 400)

  assert observe(consistency, 500, changing=True).reason == "laneChangeTransition"
  assert not observe(consistency, 600).ready
  assert observe(consistency, 1_100).ready
  consistency.note_lane_change_completed(1_100)

  assert observe(consistency, 1_200).reason == "cooldown"
  assert observe(consistency, 2_000, steering=True).reason == "driverSteering"
  assert observe(consistency, 2_500).reason == "cooldown"
  assert observe(consistency, 3_000).reason == "cooldown"
  assert observe(consistency, 3_500).ready


def test_same_navigation_event_has_a_bounded_relative_lane_change_count():
  consistency = tracker(max_changes=2)
  observe(consistency, 0)
  assert observe(consistency, 500).ready
  consistency.note_lane_change_completed(500)
  observe(consistency, 2_500)
  assert observe(consistency, 3_000).ready
  consistency.note_lane_change_completed(3_000)

  observe(consistency, 5_000)
  status = observe(consistency, 5_500)

  assert not status.ready
  assert status.reason == "changeLimit"
  assert status.completed_changes == 2


def test_new_route_revision_resets_edge_and_change_history():
  consistency = tracker(max_changes=1)
  observe(consistency, 0)
  observe(consistency, 500)
  consistency.note_lane_change_completed(500)
  assert observe(consistency, 2_500).reason == "changeLimit"

  fresh = consistency.update(
    ("session-a", 2, 8), direction="left", neighbor_exists=True,
    observation_valid=True, lane_change_active=False, steering_pressed=False, now_ns=2_500,
  )

  assert not fresh.ready
  assert fresh.completed_changes == 0
