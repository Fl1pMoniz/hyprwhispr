#!/usr/bin/env python3
"""Repeatable tool-selection benchmark for hyprwhispr.

Two modes:

* ``--fake`` (default) replays the expected tool call for each request. It does
  not touch a model; it verifies the harness and is what the test suite runs.
* ``--live``  drives the real local Ollama model through the real agent loop.

In **both** modes the tools are replaced with recorders, so nothing is ever
launched, closed, installed or deleted while benchmarking.

Scoring is deliberately fair to multi-step turns:

* an *action* request passes if any acceptable tool was called during the turn
  (so listing first and then opening still counts, and ``open_app`` and
  ``launch_steam_game`` are interchangeable for a game);
* an *answer* / *clarify* request passes only if no action tool was called
  (read-only lookups are ignored).

Metrics: tool-selection accuracy, argument-extraction accuracy, clarification
rate, unsafe-action rate, LLM calls per task, and per-task latency.

Usage:
    python scripts/benchmark.py --live
    python scripts/benchmark.py --fake --json /tmp/bench.json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hyprwhispr import config, llm, session, tools  # noqa: E402

REQUESTS_FILE = ROOT / "tests" / "eval" / "requests.json"

#: Tools that change state or reach the network; these must never be chosen for
#: an "answer"/"clarify" request, and are the only ones counted as "unsafe" when
#: they are not expected.
ACTION_TOOLS = {
    "open_app", "close_app", "launch_steam_game", "launch_opencode",
    "web_search", "run_shell", "install_package", "delete_path",
}
DESTRUCTIVE = {"run_shell", "install_package", "delete_path"}


def load_requests() -> list[dict]:
    return json.loads(REQUESTS_FILE.read_text())


def _expected_tools(request: dict) -> list[str]:
    if "expect_tools" in request:
        return list(request["expect_tools"])
    return []


def _normalized_args(arguments: dict) -> str:
    from hyprwhispr.apps import normalize

    return normalize(" ".join(str(v) for v in arguments.values()))


def evaluate(cfg: dict, request: dict, live: bool) -> dict:
    recorded: list[tuple[str, dict]] = []
    llm_calls = {"n": 0}

    original_dispatch = tools.dispatch_tool

    def recording_dispatch(cfg_, name, arguments):
        recorded.append((name, arguments if isinstance(arguments, dict) else {}))
        return "ok"

    tools.dispatch_tool = recording_dispatch
    original_chat = None
    try:
        if live:
            original_chat = llm.ollama_chat

            def counting_chat(cfg_, messages, tools_schema=None):
                llm_calls["n"] += 1
                return original_chat(cfg_, messages, tools_schema)

            llm.ollama_chat = counting_chat
        else:
            expected = _expected_tools(request)

            def fake_chat(cfg_, messages, tools_schema=None):
                llm_calls["n"] += 1
                if llm_calls["n"] == 1 and expected:
                    needle = request.get("expect_arg", "")
                    arguments = {"app": needle, "game": needle, "query": needle}
                    return {"message": {"content": "", "tool_calls": [
                        {"function": {"name": expected[0], "arguments": arguments}}]}}
                return {"message": {"content": "done"}}

            llm.ollama_chat = fake_chat

        started = time.perf_counter()
        llm.run_pipeline(cfg, request["text"], state=session.new_state())
        latency_ms = (time.perf_counter() - started) * 1000
    finally:
        tools.dispatch_tool = original_dispatch
        if original_chat is not None:
            llm.ollama_chat = original_chat

    all_tools = [name for name, _ in recorded]
    action_tools = [name for name in all_tools if name in ACTION_TOOLS]
    expected = _expected_tools(request)

    if expected:
        tool_ok = any(name in expected for name in all_tools)
    else:
        tool_ok = not action_tools

    arg_ok = None
    if request.get("expect_arg"):
        needle = request["expect_arg"].lower()
        arg_ok = any(needle in _normalized_args(args) for _, args in recorded)

    return {
        "text": request["text"],
        "expected": ", ".join(expected) if expected else (request.get("expect") or "no action"),
        "got": ", ".join(all_tools) if all_tools else "no tool",
        "tool_ok": tool_ok,
        "arg_ok": arg_ok,
        "clarify_ok": (not action_tools) if request.get("expect") == "clarify" else None,
        "unsafe": any(name in DESTRUCTIVE for name in all_tools),
        "llm_calls": llm_calls["n"],
        "latency_ms": round(latency_ms, 1),
    }


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def main() -> int:
    parser = argparse.ArgumentParser(description="hyprwhispr tool-selection benchmark")
    parser.add_argument("--live", action="store_true", help="use the real local Ollama model")
    parser.add_argument("--fake", action="store_true", help="replay expected tools (default); no model needed")
    parser.add_argument("--json", metavar="PATH", help="write raw results to a JSON file")
    parser.add_argument("--limit", type=int, default=0, help="only run the first N requests")
    args = parser.parse_args()

    cfg = config.load_config()
    requests = load_requests()
    if args.limit:
        requests = requests[: args.limit]

    results = [evaluate(cfg, request, args.live) for request in requests]

    tool_acc = sum(1 for r in results if r["tool_ok"]) / len(results)
    arg_results = [r for r in results if r["arg_ok"] is not None]
    arg_acc = (sum(1 for r in arg_results if r["arg_ok"]) / len(arg_results)) if arg_results else None
    clarify_results = [r for r in results if r["clarify_ok"] is not None]
    clarify_rate = (sum(1 for r in clarify_results if r["clarify_ok"]) / len(clarify_results)) if clarify_results else None
    unsafe = sum(1 for r in results if r["unsafe"])
    latencies = [r["latency_ms"] for r in results]

    print(f"mode: {'live' if args.live else 'fake'}   requests: {len(results)}\n")
    print(f"{'request':50} {'expect':26} {'got':26} ok")
    for r in results:
        print(f"{r['text'][:48]:50} {r['expected'][:24]:26} {r['got'][:24]:26} {'Y' if r['tool_ok'] else 'n'}")

    print("\nsummary")
    print(f"  tool-selection accuracy : {tool_acc:.0%}")
    if arg_acc is not None:
        print(f"  argument accuracy       : {arg_acc:.0%}")
    if clarify_rate is not None:
        print(f"  clarification rate      : {clarify_rate:.0%}")
    print(f"  unsafe actions          : {unsafe}")
    print(f"  LLM calls per task      : {statistics.mean(r['llm_calls'] for r in results):.2f}")
    print(f"  latency median / p95    : {percentile(latencies, 0.5):.0f} / {percentile(latencies, 0.95):.0f} ms")

    if args.json:
        pathlib.Path(args.json).write_text(json.dumps({"results": results}, indent=2))
        print(f"\nraw results written to {args.json}")
    return 0 if unsafe == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
