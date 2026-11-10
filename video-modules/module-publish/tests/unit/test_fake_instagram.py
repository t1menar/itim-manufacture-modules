import pytest

from publish.instagram.fake import FakeInstagramClient


@pytest.mark.asyncio
async def test_fake_publish_and_reconcile():
    client = FakeInstagramClient(dry_run=True)
    res = await client.publish_reel(
        account_id="acc-1",
        video_ref="s3://manufacture/x/final.mp4",
        caption="hello #pg",
        intent_id="00000000-0000-7000-8000-000000000001",
    )
    assert res.external_post_id.startswith("fake_acc-1_")
    assert "instagram.com/reel/" in res.url
    found = await client.reconcile(account_id="acc-1", external_post_id=res.external_post_id)
    assert found is not None
    assert found["dry_run"] is True
    assert await client.reconcile(account_id="acc-1", external_post_id="missing") is None
