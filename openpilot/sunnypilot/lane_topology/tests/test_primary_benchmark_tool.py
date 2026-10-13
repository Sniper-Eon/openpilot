import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]


def test_primary_benchmark_is_additive_and_reports_no_production_hook():
  source = (ROOT / "tools/benchmark_primary_lane_topology.py").read_text()
  ast.parse(source)
  assert '"gpu_used": False' in source
  assert '"production_hooked": False' in source
  assert "modeld" not in source
