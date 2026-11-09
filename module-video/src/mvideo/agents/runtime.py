"""Runs inside the agent container (05 section 4): one Claude Agent SDK session.

Reads `/job/run.json`, runs the SDK, writes every message as a JSON line to `/out/_transcript.jsonl`
and the facts of the run to `/out/_result.json`. The SDK is imported lazily: only the agent image
has it. Verified against claude-agent-sdk 0.2.179 and Claude Code 2.1.319; every option value
comes from `run.json`, so a renamed option needs a change here only.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import sys
from pathlib import Path
from typing import Any

from mvideo.agents.auth import ALL_AUTH_VARS, scrub
from mvideo.validate.rules import RuleConfig
from mvideo.validate.runner import FILES, validate_documents
from mvideo.validate.source import DirSource

# ---- tools (plain functions, wrapped for the SDK in `build_server`) ------------------------------


def _load_docs(*dirs: Path) -> tuple[dict[str, Any], list[str]]:
    docs: dict[str, Any] = {}
    problems: list[str] = []
    for d in dirs:  # later directories win: /out over /in
        for name in FILES:
            f = d / name
            if f.is_file():
                try:
                    docs[name] = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    problems.append(f"{name}: cannot read JSON: {exc}")
    return docs, problems


def validate_tool(
    in_dir: Path, out_dir: Path, src_dir: Path | None, settings: dict[str, Any] | None
) -> dict[str, Any]:
    """Validate the files of /out together with the inputs of /in (the rules span several files)."""
    docs, problems = _load_docs(in_dir, out_dir)
    only_out = {n: d for n, d in docs.items() if (out_dir / n).is_file()}
    source = DirSource(src_dir) if src_dir and src_dir.is_dir() else None
    report = validate_documents(docs, source=source, cfg=RuleConfig.from_settings(settings))
    issues = [i.as_dict() for i in report.issues if i.file in only_out or not i.file]
    return {
        "ok": not issues and not problems,
        "checked": sorted(only_out),
        "issues": issues,
        "unreadable": problems,
    }


def estimate_tool(
    out_dir: Path, in_dir: Path, settings: dict[str, Any] | None, reading_wps: float
) -> dict[str, Any]:
    from mvrender.timing import Timing, estimate

    docs, _ = _load_docs(in_dir, out_dir)
    script = docs.get("script.en.json")
    if script is None:
        return {"error": "script.en.json not found"}
    est = estimate(script, Timing.from_settings((settings or {}).get("timing")), reading_wps)
    return {"total_s": round(est.total_s, 2), "scenes": [round(s.duration, 2) for s in est.scenes]}


def source_line_tool(src_dir: Path, file: str, line: int) -> dict[str, Any]:
    src = DirSource(src_dir)
    text = src.line(file, line)
    return {"file": file, "line": line, "text": text, "exists": text is not None}


# ---- the run -------------------------------------------------------------------------------------


def _jsonable(msg: Any) -> Any:
    if dataclasses.is_dataclass(msg) and not isinstance(msg, type):
        return {"type": type(msg).__name__, **dataclasses.asdict(msg)}
    return {"type": type(msg).__name__, "repr": repr(msg)}


def _secrets() -> list[str]:
    return [v for k, v in os.environ.items() if k in ALL_AUTH_VARS and v]


def build_options(run: dict[str, Any], sdk: Any, extra_servers: dict[str, Any]) -> Any:
    kwargs: dict[str, Any] = {
        "cwd": run.get("cwd", "/work"),
        "model": run["model"],
        "max_turns": run["max_turns"],
        "allowed_tools": run["allowed_tools"],
        "disallowed_tools": run["disallowed_tools"],
        "permission_mode": run["permission_mode"],
        "setting_sources": run["setting_sources"],
        "system_prompt": {"type": "preset", "preset": "claude_code"},
        "mcp_servers": {**extra_servers, **(run.get("mcp_servers") or {})},
    }
    if run.get("max_budget_usd"):
        kwargs["max_budget_usd"] = run["max_budget_usd"]
    if run.get("resume"):
        kwargs["resume"] = run["resume"]
    return sdk.ClaudeAgentOptions(**kwargs)


def build_server(sdk: Any, run: dict[str, Any], in_dir: Path, out_dir: Path, src_dir: Path) -> Any:
    settings = run.get("settings")

    def reply(data: dict[str, Any]) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}

    @sdk.tool("validate", "Validate the JSON files you wrote to /out against the schemas and rules.", {})
    async def validate(_args: dict[str, Any]) -> dict[str, Any]:
        return reply(validate_tool(in_dir, out_dir, src_dir, settings))

    @sdk.tool("estimate", "Estimate the video length of /out/script.en.json.", {})
    async def estimate(_args: dict[str, Any]) -> dict[str, Any]:
        return reply(estimate_tool(out_dir, in_dir, settings, float(run.get("reading_wps") or 2.6)))

    @sdk.tool(
        "source_line",
        "Read one line of the pinned source: file and 1-based line.",
        {"file": str, "line": int},
    )
    async def source_line(args: dict[str, Any]) -> dict[str, Any]:
        return reply(source_line_tool(src_dir, str(args["file"]), int(args["line"])))

    return sdk.create_sdk_mcp_server("manufacture", "1.0.0", [validate, estimate, source_line])


async def run_session(run: dict[str, Any], out_dir: Path, in_dir: Path, src_dir: Path) -> dict[str, Any]:
    import importlib.metadata as md

    import claude_agent_sdk as sdk

    secrets = _secrets()
    result: dict[str, Any] = {
        "sdk_version": md.version("claude-agent-sdk"),
        "cli_version": None, "session_id": run.get("resume"), "num_turns": 0, "total_cost_usd": None,
        "usage": None, "stop_reason": None, "terminal_reason": None, "subtype": None, "is_error": False,
        "api_error_status": None, "result_text": None, "errors": [], "rate_limit": None,
        "model": run["model"],
    }  # fmt: skip
    transcript = (out_dir / "_transcript.jsonl").open("a", encoding="utf-8")
    options = build_options(run, sdk, {"manufacture": build_server(sdk, run, in_dir, out_dir, src_dir)})
    try:
        async for msg in sdk.query(prompt=run["prompt"], options=options):
            transcript.write(
                scrub(json.dumps(_jsonable(msg), default=str, ensure_ascii=False), secrets) + "\n"
            )
            transcript.flush()
            name = type(msg).__name__
            if name == "SystemMessage" and getattr(msg, "subtype", "") == "init":
                data = getattr(msg, "data", {}) or {}
                result["cli_version"] = data.get("claude_code_version") or data.get("version")
                result["session_id"] = data.get("session_id") or result["session_id"]
            elif name == "RateLimitEvent":
                info = msg.rate_limit_info
                result["rate_limit"] = {"status": info.status, "resets_at": info.resets_at}
            elif name == "ResultMessage":
                result.update(
                    session_id=msg.session_id, num_turns=msg.num_turns, total_cost_usd=msg.total_cost_usd,
                    usage=msg.usage, stop_reason=msg.stop_reason, terminal_reason=msg.terminal_reason,
                    subtype=msg.subtype, is_error=msg.is_error, api_error_status=msg.api_error_status,
                    result_text=(msg.result or "")[:2000], errors=list(msg.errors or []),
                )  # fmt: skip
    except Exception as exc:
        result.update(
            is_error=True, subtype="exception", errors=[*result["errors"], f"{type(exc).__name__}: {exc}"]
        )
    finally:
        transcript.close()
    return result


def main(argv: list[str] | None = None, *, base: Path = Path("/")) -> int:
    argv = sys.argv[1:] if argv is None else argv
    run = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    out_dir, in_dir, src_dir = base / "out", base / "in", base / "src"
    result = asyncio.run(run_session(run, out_dir, in_dir, src_dir))
    secrets = _secrets()
    text = scrub(json.dumps(result, default=str, ensure_ascii=False), secrets)
    (out_dir / "_result.json").write_text(text, encoding="utf-8")
    sys.stdout.write(f"agent done: turns={result['num_turns']} error={result['is_error']}\n")
    return 0
