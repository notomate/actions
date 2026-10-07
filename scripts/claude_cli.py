"""Run the pinned Claude Code CLI with no tools and return its text response."""
from __future__ import annotations

import json
import os
import shutil
import subprocess

from common import ActionError, get_input


def credentials(purpose: str) -> dict[str, str]:
    found = {name: value for name, value in {
        "ANTHROPIC_API_KEY": get_input("anthropic-api-key"),
        "CLAUDE_CODE_OAUTH_TOKEN": get_input("claude-code-oauth-token"),
    }.items() if value}
    if not found:
        raise ActionError(f"Provide anthropic-api-key or claude-code-oauth-token for {purpose}.")
    return found


def _run(prompt: str, model: str, secrets: dict[str, str], extra_args: list[str]) -> dict:
    claude = shutil.which("claude")
    if not claude:
        raise ActionError("The Claude Code CLI is not installed.")
    # The child sees credentials but not the other action inputs.
    env = {key: value for key, value in os.environ.items() if not key.startswith("INPUT_")} | secrets
    try:
        result = subprocess.run(
            # With no tools, Claude can only answer; no turn limit is needed.
            [claude, "--print", "--output-format", "json", "--tools", "", "--strict-mcp-config",
             "--no-session-persistence", "--model", model, *extra_args],
            input=prompt, env=env, capture_output=True, text=True, encoding="utf-8", timeout=600,
        )
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
    text = str(_run(prompt, model, secrets, []).get("result") or "").strip()
    if not text:
        raise ActionError("Claude did not return a response (empty result).")
    return text


def generate_structured(prompt: str, model: str, secrets: dict[str, str], schema: dict) -> dict:
    """Return Claude's output after the CLI has validated it against the JSON Schema."""
    response = _run(prompt, model, secrets, ["--json-schema", json.dumps(schema)])
    data = response.get("structured_output")
    if not isinstance(data, dict):
        raise ActionError("Claude did not return a JSON object matching json-schema.")
    return data
