from datetime import UTC, datetime

from publish.api.admin import _accounts_view
from publish.db.models import PlatformAccount
from publish.ids import uuid7


def test_accounts_view_never_includes_token() -> None:
    acc = PlatformAccount(
        id=uuid7(),
        channel_id="itim",
        platform="instagram",
        handle="@demo",
        external_id="1784",
        enabled=True,
        access_token="DUMMY_ACCESS_TOKEN_NOT_REAL",
        updated_at=datetime.now(UTC),
    )
    view = _accounts_view([acc])[0]
    assert view["has_token"] is True
    assert view["external_id"] == "1784"
    assert view["handle"] == "@demo"
    blob = repr(view)
    assert "access_token" not in view
    assert "DUMMY_ACCESS_TOKEN_NOT_REAL" not in blob
