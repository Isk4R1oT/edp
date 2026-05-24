#!/usr/bin/env python3
"""Smoke test for edp-mcp-server — speaks MCP 2025-06-18 over stdio.

Verifies the server responds correctly to:
  initialize       → handshake with protocolVersion
  tools/list       → 4 EDP tools
  resources/list   → 2 EDP resources
  tools/call edp_show DEC-0001  → Decision payload
  resources/read decisions://active  → <edp:active> block

Usage:
  python3 smoke.py /path/to/project/.edp

Exit 0 on full pass; non-zero if any probe fails.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _send(proc: subprocess.Popen, message: dict) -> None:
    proc.stdin.write(json.dumps(message) + "\n")
    proc.stdin.flush()


def _read_one(proc: subprocess.Popen) -> dict:
    line = proc.stdout.readline()
    if not line:
        raise RuntimeError("server closed stdout unexpectedly")
    return json.loads(line)


def _call(proc: subprocess.Popen, method: str, params: dict | None = None, request_id: int = 1) -> dict:
    msg = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        msg["params"] = params
    _send(proc, msg)
    while True:
        resp = _read_one(proc)
        # Skip notifications and unrelated responses
        if resp.get("id") == request_id:
            return resp


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: smoke.py /path/to/.edp", file=sys.stderr)
        return 2
    store = Path(sys.argv[1]).resolve()
    if not store.is_dir():
        print(f"store directory does not exist: {store}", file=sys.stderr)
        return 2

    # Locate edp-mcp-server: prefer venv, fall back to PATH
    server_bin = (
        Path(sys.executable).parent / "edp-mcp-server"
        if (Path(sys.executable).parent / "edp-mcp-server").is_file()
        else shutil.which("edp-mcp-server")
    )
    if not server_bin or not Path(server_bin).is_file():
        print("ERROR: edp-mcp-server not found on PATH or in the active venv", file=sys.stderr)
        return 2

    env = os.environ.copy()
    env["EDP_STORE"] = str(store)

    proc = subprocess.Popen(
        [str(server_bin)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=env,
    )

    failures: list[str] = []

    def assert_(cond: bool, msg: str) -> None:
        sym = "✓" if cond else "✗"
        print(f"{sym} {msg}")
        if not cond:
            failures.append(msg)

    try:
        # 1) initialize
        init_resp = _call(
            proc,
            "initialize",
            params={
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "edp-smoke", "version": "1.0"},
            },
            request_id=1,
        )
        proto = init_resp.get("result", {}).get("protocolVersion", "?")
        assert_("error" not in init_resp, f"initialize OK (protocolVersion={proto})")

        # Send initialized notification
        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})

        # 2) tools/list
        tools_resp = _call(proc, "tools/list", request_id=2)
        tools = tools_resp.get("result", {}).get("tools", [])
        tool_names = {t.get("name") for t in tools}
        expected = {"edp_show", "edp_check", "edp_record", "edp_supersede"}
        assert_(expected.issubset(tool_names), f"tools/list returns 4 EDP tools (got {sorted(tool_names)})")

        # 3) resources/list
        res_resp = _call(proc, "resources/list", request_id=3)
        resources = res_resp.get("result", {}).get("resources", [])
        uris = {r.get("uri") for r in resources}
        assert_(
            "decisions://active" in uris and "events://recent" in uris,
            f"resources/list returns decisions://active and events://recent (got {sorted(uris)})",
        )

        # 4) tools/call edp_show DEC-0001  (will fail gracefully if store has no DEC-0001)
        show_resp = _call(
            proc,
            "tools/call",
            params={"name": "edp_show", "arguments": {"decision_id": "DEC-0001"}},
            request_id=4,
        )
        is_err = show_resp.get("result", {}).get("isError") or "error" in show_resp
        if is_err:
            assert_(
                False,
                "tools/call edp_show DEC-0001 failed — seed the store first: `edp record --title ... --store ...`",
            )
        else:
            content = show_resp.get("result", {}).get("content", [])
            text = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
            assert_("DEC-0001" in text or "decision" in text.lower(), "edp_show round-trips a Decision")

        # 5) resources/read decisions://active
        active_resp = _call(
            proc,
            "resources/read",
            params={"uri": "decisions://active"},
            request_id=5,
        )
        contents = active_resp.get("result", {}).get("contents", [])
        text = " ".join(c.get("text", "") for c in contents if isinstance(c, dict))
        assert_("<edp:active" in text, "decisions://active returns an <edp:active> block")

    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.terminate()

    if failures:
        print(f"\nFAIL — {len(failures)} probe(s) failed:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nPASS — edp-mcp-server speaks MCP 2025-06-18 correctly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
