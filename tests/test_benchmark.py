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


def test_script_matches_reliable_scripts():
    assert benchmark.script_matches("مرحبا بالعالم", "arabic") is True
    assert benchmark.script_matches("こんにちは", "cjk") is True
    assert benchmark.script_matches("打开浏览器", "cjk") is True
    assert benchmark.script_matches("hello world", "arabic") is False
    assert benchmark.script_matches(None, "arabic") is None
    assert benchmark.script_matches("hello", "not-a-script") is None


def test_multilingual_fixtures_exist_and_fake_mode_scores_them():
    requests = benchmark.load_requests()
    langs = {r.get("lang") for r in requests}
    assert {"pt", "uk", "es", "de", "it", "ar", "ja", "zh"} <= langs
    cfg = {"num_ctx": 2048}
    results = [benchmark.evaluate(cfg, r, live=False) for r in requests if r.get("lang")]
    assert results and all(r["tool_ok"] for r in results)
    # the answer-script signal only applies to a live model
    assert all(r["script_ok"] is None for r in results)


def test_word_error_rate():
    assert benchmark.word_error_rate("open firefox", "open firefox") == 0.0
    assert benchmark.word_error_rate("open firefox", "open firefox now") == 0.5  # insertion
    assert benchmark.word_error_rate("open firefox", "open") == 0.5  # deletion
    assert benchmark.word_error_rate("", "") == 0.0
    assert benchmark.word_error_rate("", "extra") == 1.0


def test_benchmark_results_include_stage_metrics():
    cfg = {"num_ctx": 2048}
    results = [benchmark.evaluate(cfg, r, live=False) for r in benchmark.load_requests()]
    assert results
    assert all(isinstance(r.get("metrics"), dict) and "total_ms" in r["metrics"] for r in results)
