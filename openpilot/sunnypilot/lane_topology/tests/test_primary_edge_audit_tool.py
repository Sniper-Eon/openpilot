import ast
import json
from pathlib import Path

import pytest

from openpilot.sunnypilot.lane_topology import primary_edges
from tools.audit_primary_edge_evidence import SCHEMA, audit_records, load_records

ROOT = Path(__file__).resolve().parents[4]
CURVE_X = [0.0, 10.0, 20.0, 30.0]


def curve(y: float) -> dict:
  return {"x": list(CURVE_X), "y": [y] * len(CURVE_X)}


def frame(*, stds, probs, left_edge: float, right_edge: float,
          ego_left: float = -1.75, ego_right: float = 1.75) -> dict:
  """One diagnostic record whose geometry is exact by construction."""
  return {
    "schema": SCHEMA,
    "frame_id": 1,
    "capture_mono_ns": 1,
    "event_valid": True,
    "model": {
      "laneLines": [curve(-ego_right - 3.5), curve(ego_left), curve(ego_right), curve(-ego_left + 3.5)],
      "roadEdges": [curve(left_edge), curve(right_edge)],
      "laneLineProbs": probs,
      "roadEdgeStds": stds,
    },
  }


def clean_frame() -> dict:
  """Three 3.5 m lanes with the ego in the middle, so the candidate is 2/3."""
  return frame(stds=[0.2, 0.2], probs=[0.9, 0.9, 0.9, 0.9], left_edge=-5.25, right_edge=5.25)


def audit_fixture() -> dict:
  return audit_records([
    clean_frame(),
    frame(stds=[1.6, 1.4], probs=[0.9, 0.9, 0.9, 0.9], left_edge=-5.25, right_edge=5.25),
    frame(stds=[0.2, 0.2], probs=[0.9, 0.1, 0.1, 0.9], left_edge=-5.25, right_edge=5.25),
    frame(stds=[0.2, 0.2], probs=[0.9, 0.9, 0.9, 0.9], left_edge=-6.0, right_edge=6.0),
  ])


def test_the_audit_exposes_each_layer_instead_of_only_the_first_reason():
  audit = audit_fixture()

  assert audit["reasons"]["configured_gates"] == {
    "carriagewayDirectionUnconfirmed": 1, "nonIntegralRoadWidth": 1,
    "uncertainEgoLines": 1, "uncertainRoadEdges": 1,
  }
  # The high-uncertainty frame reaches the lane line gate once the std gate is off.
  assert audit["reasons"]["road_edge_std_gate_removed"] == {
    "carriagewayDirectionUnconfirmed": 2, "nonIntegralRoadWidth": 1, "uncertainEgoLines": 1,
  }
  # With both gates off only the geometry can still refuse, and one frame does.
  assert audit["reasons"]["confidence_gates_removed"] == {
    "carriagewayDirectionUnconfirmed": 3, "nonIntegralRoadWidth": 1,
  }


def test_the_audit_reports_whether_any_candidate_survives_the_gates():
  audit = audit_fixture()["with_confidence_gates_removed"]

  assert audit["frames_with_any_candidate"] == 3
  assert audit["candidate_index_slash_count"] == {"2/3": 3, "None/None": 1}
  assert audit["ego_lane_width_m_p10_p50_p90"] == [3.5, 3.5, 3.5]


def test_the_audit_reports_the_confidence_distributions_it_gates_on():
  audit = audit_fixture()

  assert audit["road_edge_std"]["frames_both_within"]["0.35"] == 3
  assert audit["road_edge_std"]["frames_both_within"]["1.5"] == 3
  assert audit["road_edge_std"]["frames_both_within"]["2.0"] == 4
  fractions = [slot["fraction_at_least_config"] for slot in audit["lane_line_prob"]]
  assert fractions == [1.0, 0.75, 0.75, 1.0]
  assert audit["frames"] == 4


def test_the_audit_restores_the_shipped_gates_it_relaxes():
  before = (primary_edges.MAX_EDGE_STD_M, primary_edges.MIN_LINE_PROB)

  audit_fixture()

  assert (primary_edges.MAX_EDGE_STD_M, primary_edges.MIN_LINE_PROB) == before


def test_a_clean_frame_that_passes_the_gates_is_still_not_a_confirmation():
  decision = primary_edges.primary_edge_candidate(
    type("M", (), {
      "laneLines": [type("L", (), {"x": CURVE_X, "y": [y] * 4})() for y in (-5.25, -1.75, 1.75, -5.25)],
      "roadEdges": [type("L", (), {"x": CURVE_X, "y": [y] * 4})() for y in (-5.25, 5.25)],
      "laneLineProbs": [0.9] * 4, "roadEdgeStds": [0.2, 0.2],
    })(),
  )

  assert decision.candidate_index == 2 and decision.candidate_count == 3
  assert decision.absolute_confirmed is False
  assert decision.reason == "carriagewayDirectionUnconfirmed"


def test_the_loader_rejects_unsupported_or_empty_input(tmp_path):
  good = tmp_path / "good.jsonl"
  good.write_text(json.dumps(clean_frame()) + "\n")
  assert len(load_records(good)) == 1

  for payload in ({"schema": "other"}, {"schema": SCHEMA}, {"schema": SCHEMA, "model": None}):
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps(payload) + "\n")
    with pytest.raises(ValueError):
      load_records(bad)

  empty = tmp_path / "empty.jsonl"
  empty.write_text("\n")
  with pytest.raises(ValueError):
    load_records(empty)


def test_the_audit_tool_is_offline_and_reuses_the_shipped_gates():
  source = (ROOT / "tools/audit_primary_edge_evidence.py").read_text()
  ast.parse(source)
  for forbidden in ("PubMaster", "SubMaster", "Params", "sendcan", "cereal", "visionipc", "camera"):
    assert forbidden not in source, forbidden
  assert "primary_edges.primary_edge_candidate" in source
