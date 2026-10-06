import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

import common
import meal_prompt

ROOT = Path(__file__).resolve().parents[1]


def test_meal_prompt_respects_timezone_and_preferences(environment, monkeypatch):
    monkeypatch.setattr(common.Settings, "now", lambda self: datetime(2026, 10, 5, 17, tzinfo=ZoneInfo("UTC")).astimezone(self.timezone))
    monkeypatch.setenv("INPUT_ANTHROPIC_API_KEY", "test-anthropic-secret")
    monkeypatch.setenv("INPUT_SERVINGS", "4")
    monkeypatch.setenv("INPUT_DIETARY_PREFERENCES", "Vegan\n$(echo example)")
    monkeypatch.setenv("INPUT_EXCLUDED_INGREDIENTS", "peanuts, shrimp")
    meal_prompt.main()
    text = environment.read_text(encoding="utf-8")
    assert "2026-10-06 Lunch and Dinner Menu" in text
    assert '"servings": 4' in text and "Vegan" in text and "peanuts, shrimp" in text
    assert "shopping list" in text and "test-anthropic-secret" not in text


def test_meal_credentials_required(environment):
    with pytest.raises(common.ActionError, match="anthropic-api-key"):
        meal_prompt.main()


def test_meal_entrypoint_without_repository_cwd(environment, monkeypatch, tmp_path):
    monkeypatch.setenv("INPUT_CLAUDE_CODE_OAUTH_TOKEN", "fake-oauth")
    result = subprocess.run([sys.executable, str(ROOT / "scripts/meal_prompt.py")], cwd=tmp_path, env=os.environ.copy(), capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "prompt<<" in environment.read_text(encoding="utf-8")


@pytest.mark.parametrize("value", ["0", "21", "2.5", "abc"])
def test_invalid_servings(environment, monkeypatch, value):
    monkeypatch.setenv("INPUT_ANTHROPIC_API_KEY", "fake")
    monkeypatch.setenv("INPUT_SERVINGS", value)
    with pytest.raises(common.ActionError, match="servings"):
        meal_prompt.main()


def test_reject_comment_trigger_before_invoking_upstream(environment, monkeypatch, tmp_path):
    event = tmp_path / "comment.json"
    event.write_text(json.dumps({"event": "comment.created", "workspace": {"id": "w"}}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    with pytest.raises(common.ActionError, match="schedule"):
        common.Settings.read()


def load(path):
    # BaseLoader follows string keys: YAML 1.1 SafeLoader incorrectly treats `on` as True.
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_manifests_bind_inputs_outputs_and_existing_scripts():
    for file in (ROOT / "actions").glob("*/action.yml"):
        action = load(file)
        assert action["runs"]["using"] == "composite"
        steps = action["runs"]["steps"]
        ids = {step["id"] for step in steps if "id" in step}
        for output in action["outputs"].values():
            assert re.search(r"steps\.([\w-]+)\.outputs", output["value"])[1] in ids
        referenced = set()
        for step in steps:
            for value in (*step.get("env", {}).values(), *step.get("with", {}).values()):
                referenced.update(re.findall(r"inputs\.([\w-]+)", value))
            if "run" in step:
                assert step["shell"] == "bash"
                assert "${{" not in step["run"]  # Inputs are passed through env, never interpolated into code.
                for path in re.findall(r'\$ACTION_PATH/([^"\s]+)', step["run"]):
                    assert (file.parent / path).resolve().is_file()
        assert referenced == set(action["inputs"])
        assert action["inputs"]["note-visibility"]["default"] == "private"


def test_examples_match_action_interfaces_and_cron():
    expected = {"rss-digest.yml": "0 23 * * *", "daily-meal-plan.yml": "0 0 * * *", "stocks-digest.yml": "0 1 * * *"}
    for file in (ROOT / "examples").glob("*.yml"):
        workflow = load(file)
        assert "workflow_dispatch" in workflow["on"]
        assert workflow["on"]["schedule"][0]["cron"] == expected[file.name]
        for job in workflow["jobs"].values():
            for step in job["steps"]:
                path = step["uses"].split("@", 1)[0].split("/", 2)[2]
                action = load(ROOT / path / "action.yml")
                assert set(step["with"]) <= set(action["inputs"])
                required = {key for key, value in action["inputs"].items() if value.get("required") == "true"}
                assert required <= set(step["with"])


def test_meal_upstream_publication_and_outputs():
    action = load(ROOT / "actions/daily-meal-plan/action.yml")
    upstream = action["runs"]["steps"][-1]
    assert upstream["with"]["publish-note"] == "true"
    assert upstream["with"]["direct-prompt"] == "${{ steps.prompt.outputs.prompt }}"
    assert upstream["with"]["allowed-tools"] == ","
    assert action["outputs"]["note-id"]["value"] == "${{ steps.claude.outputs.note-id }}"
