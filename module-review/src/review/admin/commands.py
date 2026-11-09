"""Parse and dispatch admin bot commands (D20). Fake-Telegram friendly."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from review.admin.allowlist import AdminAllowlist
from review.clients.core_admin import CoreAdminClient


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    text: str
    status_code: int | None = None


class AdminCommands:
    def __init__(self, client: CoreAdminClient, allowlist: AdminAllowlist) -> None:
        self._client = client
        self._allowlist = allowlist

    async def handle(self, telegram_user_id: int, text: str) -> CommandResult:
        if not self._allowlist.contains(telegram_user_id):
            return CommandResult(False, "forbidden: not an admin")
        parts = text.strip().split()
        if not parts:
            return CommandResult(False, "empty command")
        cmd = parts[0].lower()
        try:
            if cmd == "/republish" and len(parts) >= 4:
                intent = UUID(parts[1])
                gen = int(parts[2])
                reason = " ".join(parts[3:])
                res = await self._client.republish(
                    intent, reason=reason, base_generation=gen, telegram_user_id=telegram_user_id
                )
                return CommandResult(res.is_success, f"republish → {res.status_code}", res.status_code)
            if cmd == "/module" and len(parts) >= 3:
                action, module_id = parts[1].lower(), parts[2]
                if action == "on":
                    res = await self._client.activate_module(module_id, telegram_user_id=telegram_user_id)
                elif action == "off":
                    res = await self._client.deactivate_module(module_id, telegram_user_id=telegram_user_id)
                else:
                    return CommandResult(False, "usage: /module on|off <id>")
                return CommandResult(res.is_success, f"module {action} → {res.status_code}", res.status_code)
            if cmd == "/retry" and len(parts) == 2:
                res = await self._client.retry_variant(UUID(parts[1]), telegram_user_id=telegram_user_id)
                return CommandResult(res.is_success, f"retry → {res.status_code}", res.status_code)
            if cmd == "/skip" and len(parts) >= 3:
                res = await self._client.skip_variant(
                    UUID(parts[1]), reason=" ".join(parts[2:]), telegram_user_id=telegram_user_id
                )
                return CommandResult(res.is_success, f"skip → {res.status_code}", res.status_code)
            if cmd == "/settings" and len(parts) == 1:
                res = await self._client.get_core_settings(telegram_user_id=telegram_user_id)
                body = res.text[:500] if res.is_success else res.text[:200]
                return CommandResult(res.is_success, f"settings → {res.status_code}\n{body}", res.status_code)
        except Exception as exc:
            return CommandResult(False, f"error: {exc}")
        return CommandResult(
            False,
            "commands: /republish <intent> <base_gen> <reason> | /module on|off <id> | "
            "/retry <variant> | /skip <variant> <reason> | /settings",
        )
