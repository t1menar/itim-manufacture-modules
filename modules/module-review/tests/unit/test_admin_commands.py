from __future__ import annotations

import httpx
import pytest
import respx

from review.admin.allowlist import AdminAllowlist
from review.admin.commands import AdminCommands
from review.clients.core_admin import CoreAdminClient
from review.telegram.fake import FakeTelegramBot


@pytest.mark.asyncio
@respx.mock
async def test_allowlist_and_module_off() -> None:
    respx.post("http://core.test/internal/v1/modules/vidmod/deactivate").mock(
        return_value=httpx.Response(204)
    )
    cmds = AdminCommands(
        CoreAdminClient("http://core.test", "mfa_test_admin_token_xxxxxxxx"),
        AdminAllowlist([42]),
    )
    denied = await cmds.handle(7, "/module off vidmod")
    assert denied.ok is False and "forbidden" in denied.text
    ok = await cmds.handle(42, "/module off vidmod")
    assert ok.ok is True and ok.status_code == 204


@pytest.mark.asyncio
@respx.mock
async def test_fake_telegram_roundtrip() -> None:
    respx.post(url__regex=r".*/variants/.*/retry").mock(
        return_value=httpx.Response(200, json={"job_id": "j"})
    )
    bot = FakeTelegramBot()
    cmds = AdminCommands(
        CoreAdminClient("http://core.test", "mfa_test_admin_token_xxxxxxxx"),
        AdminAllowlist([1]),
    )
    bot.push_message(chat_id=9, user_id=1, text="/retry 01900000-0000-7000-8000-000000000099")
    for upd in bot.poll():
        result = await cmds.handle(upd.user_id, upd.text)
        await bot.send_message(upd.chat_id, result.text)
    assert bot.sent and "retry → 200" in bot.sent[0]["text"]
