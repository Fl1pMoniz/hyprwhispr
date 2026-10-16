import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location("benchmark", ROOT / "scripts" / "benchmark.py")
benchmark = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(benchmark)


def test_benchmark_harness_fake_mode_is_accurate():
    cfg = {"num_ctx": 2048}
    results = [benchmark.evaluate(cfg, request, live=False) for request in benchmark.load_requests()]
    assert results, "expected some evaluation requests"
    assert all(r["tool_ok"] for r in results), [r for r in results if not r["tool_ok"]]
    arg_results = [r for r in results if r["arg_ok"] is not None]
    assert arg_results and all(r["arg_ok"] for r in arg_results)


def test_benchmark_never_records_a_destructive_action():
    cfg = {"num_ctx": 2048}
    results = [benchmark.evaluate(cfg, request, live=False) for request in benchmark.load_requests()]
    assert not any(r["unsafe"] for r in results)
