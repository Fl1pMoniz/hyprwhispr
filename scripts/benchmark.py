#!/usr/bin/env python3
"""Repeatable evaluation harness for hyprwhispr.

Two modes for the **text** request set:

* ``--fake`` (default) replays the expected tool call for each request. It does
  not touch a model; it verifies the harness and is what the test suite runs.
* ``--live``  drives the real local Ollama model through the real agent loop.

In **both** modes the tools are replaced with recorders, so nothing is ever
launched, closed, installed or deleted while benchmarking.

What the text fixtures measure: tool selection (overall and per language, via the
``lang`` field), argument extraction, clarification behaviour, unsafe-action
rate, and - for a live model on non-Latin fixtures - whether the reply uses the
expected script. They do **not** measure speech-recognition quality: the text is
given directly to the agent, so no audio or Whisper is involved.

Audio is measured separately, both optional and local:

* ``--transcribe FILE.wav``  time a single local transcription.
* ``--wer MANIFEST.json``    transcribe a list of local recordings and compute
  word error rate against a reference transcript (only when a reference is
  present). Add ``--show-text`` to print the recognized text too.

Metrics: tool-selection accuracy (overall / multilingual subset), argument
accuracy, clarification rate, unsafe-action rate, LLM calls per task, and
per-stage latency (total, LLM, tool) with sample counts.

Usage:
    python scripts/benchmark.py                       # harness only, no model
    python scripts/benchmark.py --live                # real local model
    python scripts/benchmark.py --transcribe clip.wav # time one transcription
    python scripts/benchmark.py --wer manifest.json   # WER vs references
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
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

#: Unicode ranges used for the (reliable, script-based) answer-language check.
_SCRIPT_RANGES = {
    "arabic": [(0x0600, 0x06FF), (0x0750, 0x077F)],
    "cjk": [(0x3040, 0x30FF), (0x4E00, 0x9FFF)],  # kana + CJK unified
    "cyrillic": [(0x0400, 0x04FF)],
    "greek": [(0x0370, 0x03FF)],
}


def load_requests() -> list[dict]:
    return json.loads(REQUESTS_FILE.read_text())


def _expected_tools(request: dict) -> list[str]:
    if "expect_tools" in request:
        return list(request["expect_tools"])
    return []


def _normalized_args(arguments: dict) -> str:
    from hyprwhispr.apps import normalize

    return normalize(" ".join(str(v) for v in arguments.values()))


def script_matches(text: str | None, name: str) -> bool | None:
    """True if *text* contains a character of the named script, else False/None.

    Reliable for non-Latin scripts (Arabic, CJK, Cyrillic, Greek). It says
    nothing about grammar or about Latin languages, so those are not scored.
    """
    ranges = _SCRIPT_RANGES.get(name)
    if not ranges or not text:
        return None
    for char in text:
        codepoint = ord(char)
        if any(low <= codepoint <= high for low, high in ranges):
            return True
    return False


def _words(text: str | None) -> list[str]:
    return re.findall(r"\w+", (text or "").lower(), flags=re.UNICODE)


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Levenshtein word error rate. Returns edits / len(reference words)."""
    ref = _words(reference)
    hyp = _words(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    previous = list(range(len(hyp) + 1))
    for i, ref_word in enumerate(ref, 1):
        current = [i]
        for j, hyp_word in enumerate(hyp, 1):
            cost = 0 if ref_word == hyp_word else 1
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost))
        previous = current
    return previous[-1] / len(ref)


def _fake_result(name: str, arguments: dict) -> str:
    """A realistic, non-executing tool result so the model can finish the turn."""
    target = arguments.get("app") or arguments.get("game") or ""
    if name == "open_app":
        return f"opened {target}" if target else "opened the app"
    if name == "close_app":
        return f"closed {target}" if target else "closed the app"
    if name == "launch_steam_game":
        return f"launching the Steam game {target}" if target else "launched the game"
    if name == "list_apps":
        return "listed the installed apps"
    if name == "list_steam_games":
        return "listed the installed Steam games"
    if name == "web_search":
        return f"opened a web search for '{arguments.get('query', '')}'"
    if name == "remember":
        return f"remembered '{arguments.get('key', '')}'"
    if name == "recall":
        return "remembered: (none yet)"
    if name == "launch_opencode":
        return "opened OpenCode in a new terminal window"
    return "done"


def evaluate(cfg: dict, request: dict, live: bool) -> dict:
    recorded: list[tuple[str, dict]] = []
    llm_calls = {"n": 0}
    metrics: dict = {}

    original_dispatch = tools.dispatch_tool

    def recording_dispatch(cfg_, name, arguments):
        recorded.append((name, arguments if isinstance(arguments, dict) else {}))
        return _fake_result(name, arguments if isinstance(arguments, dict) else {})

    tools.dispatch_tool = recording_dispatch
    original_chat = llm.ollama_chat  # always capture so we always restore
    try:
        if live:

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
        answer = llm.run_pipeline(cfg, request["text"], state=session.new_state(), metrics=metrics)
        latency_ms = (time.perf_counter() - started) * 1000
    finally:
        tools.dispatch_tool = original_dispatch
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
        "lang": request.get("lang"),
        "expected": ", ".join(expected) if expected else (request.get("expect") or "no action"),
        "got": ", ".join(all_tools) if all_tools else "no tool",
        "tool_ok": tool_ok,
        "arg_ok": arg_ok,
        "clarify_ok": (not action_tools) if request.get("expect") == "clarify" else None,
        "unsafe": any(name in DESTRUCTIVE for name in all_tools),
        "answer": answer,
        # only meaningful for a live model + a non-Latin fixture
        "script_ok": script_matches(answer, request["expect_script"])
        if (live and request.get("expect_script")) else None,
        "llm_calls": llm_calls["n"],
        "latency_ms": round(latency_ms, 1),
        "metrics": metrics,
    }


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def _accuracy(subset: list[dict]) -> float | None:
    return (sum(1 for r in subset if r["tool_ok"]) / len(subset)) if subset else None


def _stage(results: list[dict], key: str) -> list[float]:
    out = []
    for r in results:
        value = (r.get("metrics") or {}).get(key)
        if value is not None:
            out.append(value)
    return out


def measure_transcription(cfg: dict, wav: str) -> int:
    """Time a single local transcription (needs the whisper.cpp model)."""
    from hyprwhispr import speech

    started = time.perf_counter()
    text, error = speech.transcribe(cfg, wav)
    elapsed_ms = (time.perf_counter() - started) * 1000
    print(f"model: {cfg['whisper_model']}")
    print(f"language setting: {cfg.get('language')!r}")
    print(f"transcription latency: {elapsed_ms:.0f} ms")
    print(f"error: {error}")
    print(f"transcript: {text!r}")
    return 0 if error is None else 1


def measure_wer(cfg: dict, manifest_path: str, show_text: bool) -> int:
    """Transcribe local recordings and compute WER where a reference exists."""
    from hyprwhispr import speech

    entries = json.loads(pathlib.Path(manifest_path).read_text())
    rows = []
    for entry in entries:
        started = time.perf_counter()
        text, error = speech.transcribe(cfg, entry["audio"])
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        reference = entry.get("reference")
        wer = word_error_rate(reference, text) if (error is None and reference is not None) else None
        rows.append(wer)
        wer_text = "n/a" if wer is None else f"{wer:.2f}"
        print(f"{entry['audio']:44} lang={entry.get('lang') or '-':3} ms={elapsed_ms:5} wer={wer_text} err={error}")
        if show_text:
            print(f"    recognized: {text!r}")
    valid = [w for w in rows if w is not None]
    if valid:
        print(f"\nmean WER: {statistics.mean(valid):.2f}  (n={len(valid)}; references required)")
    else:
        print("\nno references supplied; WER not computed (need audio + reference transcript)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="hyprwhispr evaluation harness")
    parser.add_argument("--live", action="store_true", help="use the real local Ollama model")
    parser.add_argument("--fake", action="store_true", help="replay expected tools (default); no model needed")
    parser.add_argument("--json", metavar="PATH", help="write raw results to a JSON file")
    parser.add_argument("--limit", type=int, default=0, help="only run the first N requests")
    parser.add_argument("--transcribe", metavar="WAV", help="time a single transcription and exit")
    parser.add_argument("--wer", metavar="MANIFEST", help="WER over local recordings listed in a JSON manifest")
    parser.add_argument("--show-text", action="store_true", help="with --wer, also print recognized text")
    args = parser.parse_args()

    cfg = config.load_config()
    if args.transcribe:
        return measure_transcription(cfg, args.transcribe)
    if args.wer:
        return measure_wer(cfg, args.wer, args.show_text)

    requests = load_requests()
    if args.limit:
        requests = requests[: args.limit]

    results = [evaluate(cfg, request, args.live) for request in requests]

    tool_acc = _accuracy(results)
    multilingual = [r for r in results if r["lang"] not in (None, "en")]
    multilingual_acc = _accuracy(multilingual)
    arg_results = [r for r in results if r["arg_ok"] is not None]
    arg_acc = (sum(1 for r in arg_results if r["arg_ok"]) / len(arg_results)) if arg_results else None
    clarify_results = [r for r in results if r["clarify_ok"] is not None]
    clarify_rate = (sum(1 for r in clarify_results if r["clarify_ok"]) / len(clarify_results)) if clarify_results else None
    script_results = [r for r in results if r["script_ok"] is not None]
    unsafe = sum(1 for r in results if r["unsafe"])

    print(f"mode: {'live' if args.live else 'fake'}   text requests: {len(results)}")
    print("(text fixtures measure tool selection and replies, NOT speech-recognition accuracy)\n")
    print(f"{'request':46} {'expect':24} {'got':24} ok")
    for r in results:
        marker = "Y" if r["tool_ok"] else "n"
        lang = f"[{r['lang']}]" if r["lang"] else ""
        print(f"{r['text'][:44]:46} {r['expected'][:22]:24} {r['got'][:22]:24} {marker} {lang}")

    print("\nsummary")
    print(f"  tool-selection accuracy : {tool_acc:.0%}")
    if multilingual_acc is not None:
        print(f"  multilingual subset     : {multilingual_acc:.0%}  (n={len(multilingual)})")
    if arg_acc is not None:
        print(f"  argument accuracy       : {arg_acc:.0%}")
    if clarify_rate is not None:
        print(f"  clarification rate      : {clarify_rate:.0%}")
    if script_results:
        print(f"  answer-script match     : {sum(1 for r in script_results if r['script_ok'])}/{len(script_results)}  (live only)")
    print(f"  unsafe actions          : {unsafe}")
    print(f"  LLM calls per task      : {statistics.mean(r['llm_calls'] for r in results):.2f}")

    total = _stage(results, "total_ms")
    llm_ms = _stage(results, "llm_ms")
    tool_ms = _stage(results, "tool_ms")
    if total:
        print(f"  total ms  median / p95  : {percentile(total, 0.5):.0f} / {percentile(total, 0.95):.0f}  (n={len(total)})")
    if llm_ms:
        print(f"  llm   ms  median / p95  : {percentile(llm_ms, 0.5):.0f} / {percentile(llm_ms, 0.95):.0f}  (n={len(llm_ms)})")
    if tool_ms:
        print(f"  tool  ms  median / p95  : {percentile(tool_ms, 0.5):.0f} / {percentile(tool_ms, 0.95):.0f}  (n={len(tool_ms)})")
    per_call = [ms for r in results for ms in (r.get("metrics") or {}).get("llm_call_ms", [])]
    if per_call:
        print(f"  per LLM call ms med/max : {percentile(per_call, 0.5):.0f} / {max(per_call):.0f}  (n={len(per_call)})")
    prompt_tok = sum((r.get("metrics") or {}).get("llm_prompt_tokens", 0) for r in results)
    eval_tok = sum((r.get("metrics") or {}).get("llm_eval_tokens", 0) for r in results)
    load_ms = sum((r.get("metrics") or {}).get("llm_load_ms", 0) for r in results)
    if eval_tok or prompt_tok:
        print(f"  tokens prompt/eval      : {prompt_tok} / {eval_tok}  (model load {load_ms} ms total)")

    if args.json:
        pathlib.Path(args.json).write_text(json.dumps({"results": results}, indent=2))
        print(f"\nraw results written to {args.json}")
    return 0 if unsafe == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
