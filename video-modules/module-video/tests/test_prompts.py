import json

import pytest

from mvideo.agents import prompts

STEPS = ("analysis", "research", "script", "capture", "package", "script-revise")


@pytest.mark.parametrize("step", STEPS)
def test_every_prompt_is_present_and_placeholders_match_the_spec(step: str) -> None:
    p = prompts.load_prompt(step, "1.0.0")
    meta = json.loads((prompts.PROMPTS_ROOT / step / "1.0.0" / "meta.json").read_text())
    assert p.id == f"{step}@1.0.0" and p.claude_md.startswith("# Step")
    assert set(meta["placeholders"]) <= set(meta["declared_placeholders"]) | set(meta["placeholders"])
    assert p.task_md and "{" in p.task_md


def test_render_is_strict() -> None:
    assert prompts.render("a {x} b {y}", {"x": 1, "y": "z"}) == "a 1 b z"
    with pytest.raises(prompts.PromptError):
        prompts.render("a {x} {y}", {"x": 1})


def test_analysis_task_renders_with_the_documented_values() -> None:
    p = prompts.load_prompt("analysis", "1.0.0")
    text = prompts.render(
        p.task_md,
        {
            "idea_id": 42,
            "idea_text": "CREATE DATABASE",
            "channel_name": "iTim",
            "min_s": 60,
            "max_s": 180,
            "sandbox_keys": "postgres17",
        },
    )
    assert "idea 42" in text and "{" not in text
