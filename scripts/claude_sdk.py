"""Run Claude through the Agent SDK bridge (sdk/claude.mjs) with no tools."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from common import ActionError, get_input

BRIDGE = Path(__file__).resolve().parents[1] / "sdk" / "claude.mjs"


def credentials(purpose: str) -> dict[str, str]:
    found = {name: value for name, value in {
        "ANTHROPIC_API_KEY": get_input("anthropic-api-key"),
        "CLAUDE_CODE_OAUTH_TOKEN": get_input("claude-code-oauth-token"),
    }.items() if value}
    if not found:
        raise ActionError(f"Provide anthropic-api-key or claude-code-oauth-token for {purpose}.")
    return found


def _run(prompt: str, model: str, secrets: dict[str, str], schema: dict | None) -> dict:
    node = shutil.which("node")
    if not node:
        raise ActionError("Node.js is required to run the Claude Agent SDK.")
    # The bridge sees credentials but not the other action inputs.
    env = {key: value for key, value in os.environ.items() if not key.startswith("INPUT_")} | secrets
    request = json.dumps({"prompt": prompt, "model": model, "schema": schema})
    try:
        result = subprocess.run([node, str(BRIDGE)], input=request, env=env, capture_output=True, text=True,
                                encoding="utf-8", timeout=600)
    except subprocess.TimeoutExpired:
        raise ActionError("Claude did not respond within 10 minutes.") from None
    try:
        response = json.loads(result.stdout)
    except ValueError:
        response = None
    # Claude's error text can echo request details; report only the result subtype.
    if result.returncode or not isinstance(response, dict) or response.get("is_error"):
        subtype = response.get("subtype") if isinstance(response, dict) else None
        raise ActionError(f"Claude did not return a response ({subtype or 'no result'}).")
    return response


def generate(prompt: str, model: str, secrets: dict[str, str]) -> str:
    text = str(_run(prompt, model, secrets, None).get("result") or "").strip()
    if not text:
        raise ActionError("Claude did not return a response (empty result).")
    return text


def generate_structured(prompt: str, model: str, secrets: dict[str, str], schema: dict) -> dict:
    """Return Claude's output after the SDK has validated it against the JSON Schema."""
    data = _run(prompt, model, secrets, schema).get("structured_output")
    if not isinstance(data, dict):
        raise ActionError("Claude did not return a JSON object matching json-schema.")
    return data
