"""Pydantic model of the module settings (04 section 10).

The JSON Schema served as `settings_schema` in `/info` is generated from this model, so the
admin panel form and the validation of every job snapshot share one definition.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

StepName = Literal["analysis", "research", "script", "capture", "package", "script-revise"]
Semver = Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
ImageRef = Annotated[str, Field(pattern=r"@sha256:[0-9a-f]{64}$")]
HexColor = Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")]

SETTINGS_SCHEMA_ID = "https://manufacture.local/schemas/video/settings-1.json"


class StepLimit(BaseModel):
    max_turns: int = Field(ge=1, le=200)
    budget_usd: float = Field(ge=0)
    timeout_s: int = Field(ge=30, le=3600)


def _default_steps() -> dict[str, StepLimit]:
    return {
        "analysis": StepLimit(max_turns=20, budget_usd=1.0, timeout_s=600),
        "research": StepLimit(max_turns=60, budget_usd=4.0, timeout_s=1500),
        "script": StepLimit(max_turns=40, budget_usd=3.0, timeout_s=1200),
        "capture": StepLimit(max_turns=40, budget_usd=2.0, timeout_s=1200),
        "package": StepLimit(max_turns=10, budget_usd=0.3, timeout_s=300),
        "script-revise": StepLimit(max_turns=30, budget_usd=2.0, timeout_s=900),
    }


class Limits(BaseModel):
    cost_mode: Literal["usd", "estimate"] | None = Field(
        default=None,
        description=(
            "usd: job_budget_usd and step budget_usd are enforced. estimate: not enforced, cost is "
            "computed from usage. Default: usd when agent.auth.mode is api_key, estimate when "
            "subscription (resolved at job start)."
        ),
    )
    job_budget_usd: float = Field(default=15, ge=0)
    max_jobs_per_day: int = Field(default=6, ge=1)
    max_agent_runs_per_hour: int = Field(default=12, ge=1)
    rate_limit_backoff_s: int = Field(default=900, ge=60)
    schema_retries: int = Field(default=2, ge=0, le=5)
    fix_rounds: int = Field(default=2, ge=0, le=4)
    steps: dict[str, StepLimit] = Field(default_factory=_default_steps)


class Network(BaseModel):
    anthropic_hosts: list[str] = ["api.anthropic.com"]
    allow_domains: dict[str, list[str]] = {
        "analysis": ["www.postgresql.org", "wiki.postgresql.org", "github.com"],
        "research": [
            "www.postgresql.org",
            "wiki.postgresql.org",
            "github.com",
            "raw.githubusercontent.com",
            "stackoverflow.com",
            "dba.stackexchange.com",
            "news.ycombinator.com",
        ],
        "sources": ["github.com", "codeload.github.com", "git.postgresql.org"],
    }
    proxy_ports: Annotated[list[int], Field(min_length=2, max_length=2)] = [3200, 3299]


class AgentAuth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["subscription", "api_key"] = "subscription"
    credential_ref: str = Field(
        default="cred:claude-subscription",
        description=(
            "subscription: credential kind claude_oauth_token (token from claude setup-token); "
            "api_key: kind anthropic_api_key, e.g. cred:anthropic-main"
        ),
    )


class Agent(BaseModel):
    image: ImageRef
    auth: AgentAuth = AgentAuth()
    cpus: float = 1
    memory_mb: int = 2048
    pids: int = 256


class AllowedRepo(BaseModel):
    name: str
    url: str = Field(json_schema_extra={"format": "uri"})
    refs: list[str]


class Sources(BaseModel):
    allowed_repos: list[AllowedRepo] = [
        AllowedRepo(
            name="postgres",
            url="https://github.com/postgres/postgres",
            refs=["REL_17_STABLE", "REL_16_STABLE", "master"],
        )
    ]
    cache_max_gb: float = 20


class Sandbox(BaseModel):
    cpus: float = 2
    memory_mb: int = 2048
    pids: int = 512
    command_timeout_s: int = 60
    total_timeout_s: int = 900
    ready_timeout_s: int = 60


class SandboxSession(BaseModel):
    kind: Literal["psql", "sh"] | None = None
    start: str | None = None
    title: str | None = None
    env: dict[str, Any] | None = None


class SandboxImage(BaseModel):
    image: ImageRef
    description: str | None = None
    env: dict[str, str] | None = None
    tmpfs: dict[str, str] | None = None
    cap_add: list[str] | None = None
    ready_cmd: str
    version_cmd: str
    version_expect: str
    sessions: dict[str, SandboxSession]


class DurationRange(BaseModel):
    min: float = 60
    max: float = 180


class SafeZone(BaseModel):
    top: int = 220
    bottom: int = 400
    left: int = 72
    right: int = 108


class Video(BaseModel):
    width: Literal[1080] = 1080
    height: Literal[1920] = 1920
    fps: Literal[30, 60] = 60
    crf: int = Field(default=17, ge=12, le=28)
    preset: Literal["fast", "medium", "slow"] = "medium"
    max_bitrate_kbps: int = 24000
    gop_s: float = 2
    duration_s: DurationRange = DurationRange()
    safe_zone: SafeZone = SafeZone()


class Audio(BaseModel):
    lufs: float = -14
    true_peak: float = -1.0
    lra: float = 11
    tolerance_lu: float = 0.5
    sample_rate: Literal[48000] = 48000
    bitrate_kbps: int = 128
    ambient_pad: bool = True


class Fonts(BaseModel):
    ui: Literal["Inter"] = "Inter"
    mono: Literal["JetBrains Mono"] = "JetBrains Mono"


DEFAULT_PALETTE: dict[str, str] = {
    "page": "#FBF8F3",
    "grid": "#EAE2D8",
    "ink": "#1F1B17",
    "muted": "#766C62",
    "faint": "#E0D7CC",
    "accent": "#FF6B00",
    "accent_text": "#DB5200",
    "accent_light": "#FFEDDE",
    "win": "#1E1A17",
    "win_bar": "#2C2723",
    "win_line": "#3E3731",
    "win_fg": "#F3EDE5",
    "win_muted": "#988D81",
    "win_dim": "#645C54",
    "watch_bg": "#24201C",
    "c_kw": "#FF913C",
    "c_type": "#FFCDA0",
    "c_str": "#FFE0BE",
    "c_num": "#FFAF5F",
    "c_comment": "#82786E",
    "c_fn": "#FFFFFF",
    "c_macro": "#FFA573",
    "err": "#FF6955",
    "err_cont": "#FF9682",
    "detail": "#FFBE5A",
}


class Timing(BaseModel):
    read_base_s: float = 1.0
    read_min_s: float = 2.6
    default_cps: float = 24
    step_tail_s: float = 1.0
    step_notes_pad_s: float = 0.6
    default_hold_s: float = 1.4
    scene_tail_s: float = 1.5
    fast_line_s: float = 0.14
    fade_s: float = 0.35
    dissolve_s: float = 0.18


class Text(BaseModel):
    caption_px: int = 60
    caption_min_px: int = 44
    caption_max_lines: int = 2
    hook_max_lines: int = 3
    note_max_lines: int = 2
    allowed_symbols: str = "…—–→≈×=·%/()[]{}<>:;,.!?'\"*+-_#@&"
    forbidden_patterns: list[str] = [
        "(?i)gdb session",
        "(?i)next video",
        r"(?i)part \d+ of",
        r"\b[0-9a-f]{12,40}\b",
    ]


class Sheet(BaseModel):
    cols: int = 4
    thumb_w: int = 270
    safe_overlay: bool = True


class Render(BaseModel):
    workers: int = Field(default=0, ge=0)
    chunk_s: float = 10
    glyph_sample_s: float = 0.25
    sheet: Sheet = Sheet()


class Platform(BaseModel):
    max_size_mb: int = 300


class Post(BaseModel):
    max_caption_chars: int = 2200
    max_hashtags: int = 30


class Revise(BaseModel):
    changes_max_chars: int = 1500


class Runtime(BaseModel):
    max_parallel_jobs: int = 1
    orphan_ttl_s: int = 3600
    retention_days: int = 180


class VideoSettings(BaseModel):
    """Root of the settings snapshot (`settings.values` in a job request)."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={"$id": SETTINGS_SCHEMA_ID})

    model: str = "claude-opus-5-5"
    models: dict[StepName, str] = {}
    prompt_versions: dict[str, Semver] = {
        "analysis": "1.0.0",
        "research": "1.0.0",
        "script": "1.0.0",
        "capture": "1.0.0",
        "package": "1.0.0",
        "script-revise": "1.0.0",
        "skill": "1.0.0",
    }
    limits: Limits = Limits()
    network: Network = Network()
    agent: Agent
    sources: Sources = Sources()
    sandbox: Sandbox = Sandbox()
    sandbox_images: dict[str, SandboxImage]
    video: Video = Video()
    audio: Audio = Audio()
    fonts: Fonts = Fonts()
    palette: dict[str, HexColor] = DEFAULT_PALETTE
    timing: Timing = Timing()
    text: Text = Text()
    render: Render = Render()
    platform: Platform = Platform()
    post: Post = Post()
    revise: Revise = Revise()
    runtime: Runtime = Runtime()

    def resolved_cost_mode(self) -> Literal["usd", "estimate"]:
        """`estimate` for a subscription (nothing is billed per call), `usd` for an API key."""
        if self.limits.cost_mode is not None:
            return self.limits.cost_mode
        return "usd" if self.agent.auth.mode == "api_key" else "estimate"


def settings_schema() -> dict[str, Any]:
    schema = VideoSettings.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return schema
