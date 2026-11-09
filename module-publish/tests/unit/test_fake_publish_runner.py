from __future__ import annotations

import pytest

from publish.domain.runner import result_callback_body, run_publish_intents
from publish.instagram.fake import FakeInstagramClient


@pytest.mark.asyncio
async def test_fake_runner_builds_published_output() -> None:
    client = FakeInstagramClient(dry_run=True)
    account = "0193a1d0-0000-7000-8000-000000000004"
    intent = "0193a1f0-0000-7000-8000-000000000006"
    output = await run_publish_intents(
        client=client,
        intents=[{"intent_id": intent, "platform_account_id": account, "handle": "@itim"}],
        caption="hello",
    )
    assert len(output["publications"]) == 1
    pub = output["publications"][0]
    assert pub["status"] == "published"
    assert pub["external_post_id"]
    assert pub["url"].startswith("https://www.instagram.com/reel/")
    assert pub["intent_id"] == intent
    assert pub["dry_run"] is True
    body = result_callback_body(output)
    assert body["output"] is output
    assert body["artifacts"] == []
