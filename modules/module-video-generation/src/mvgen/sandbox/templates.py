"""Container specs from the sandbox catalog.

The only place that decides how a sandbox container is configured, so the rules (no network,
no binds, no privileges, fixed limits) can be tested on the produced specification alone.
"""

from __future__ import annotations

from typing import Any

from mvgen.sandbox.config import SandboxImage, SandboxLimits

LABEL_MODULE = "manufacture.module"
FORBIDDEN_KEYS = ("volumes", "binds", "privileged", "pid_mode", "ipc_mode", "devices", "volumes_from")


class TemplateError(ValueError):
    """The settings do not describe an acceptable sandbox."""


def require_digest(ref: str) -> str:
    if "@sha256:" not in ref:
        raise TemplateError(f"sandbox image {ref!r} must be pinned by digest (@sha256:...)")
    return ref


def digest_of(ref: str) -> str:
    return "sha256:" + require_digest(ref).split("@sha256:", 1)[1]


def container_spec(
    image: SandboxImage,
    limits: SandboxLimits,
    *,
    purpose: str = "capture",
    run_id: str = "",
) -> dict[str, Any]:
    """Keyword arguments for `containers.create`, from the image entry and the sandbox limits."""
    memory = f"{limits.memory_mb}m"
    spec: dict[str, Any] = {
        "image": require_digest(image.image),
        "detach": True,
        "network_mode": "none",
        "read_only": True,
        "tmpfs": dict(image.tmpfs or {}),
        "nano_cpus": int(limits.cpus * 1_000_000_000),
        "mem_limit": memory,
        "memswap_limit": memory,  # equal to mem_limit: no swap
        "pids_limit": limits.pids,
        "cap_drop": ["ALL"],
        "cap_add": list(image.cap_add or []),
        "security_opt": ["no-new-privileges"],
        "environment": dict(image.env or {}),
        "labels": {LABEL_MODULE: "video-generation", "manufacture.purpose": purpose, "manufacture.run": run_id},
    }
    if image.hostname:
        spec["hostname"] = image.hostname
    assert not set(spec) & set(FORBIDDEN_KEYS)  # noqa: S101
    return spec


def limits_record(limits: SandboxLimits) -> dict[str, Any]:
    """The `limits` object of capture.json."""
    cpus: float | int = int(limits.cpus) if float(limits.cpus).is_integer() else limits.cpus
    return {"cpus": cpus, "memory_mb": limits.memory_mb, "pids": limits.pids, "network": "none"}
