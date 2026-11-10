"""The command consumer: job.requested reaches the service; a rejected job is reported to the core."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from typing import Any

import aio_pika
import httpx
import pytest
import respx

from mvideo.api.problems import ProblemError
from mvideo.commands import CommandConsumer, declare_command_queue
from tests.helpers import job_request
from tests.test_ideas_rabbit import connect, wait_for
from tests.test_sandbox import docker_client  # noqa: F401


class FakeService:
    def __init__(self, reject: ProblemError | None = None) -> None:
        self.accepted: list[Any] = []
        self.cancelled: list[uuid.UUID] = []
        self.reject = reject

    async def local_credentials(self) -> frozenset[str]:
        return frozenset({"CLAUDE_OAUTH_TOKEN"})

    async def accept(self, job: Any, traceparent: str | None) -> None:
        if self.reject:
            raise self.reject
        self.accepted.append((job, traceparent))

    async def cancel(self, job_id: uuid.UUID) -> tuple[str, None]:
        self.cancelled.append(job_id)
        return "cancelling", None


def envelope(kind: str, payload: dict[str, Any], job_id: uuid.UUID | None = None) -> bytes:
    body: dict[str, Any] = {"type": kind, "payload": payload, "traceparent": "00-aa-bb-01"}
    if job_id:
        body["job"] = {"job_id": str(job_id), "fence": 2}
    return json.dumps(body).encode()


async def test_job_requested_is_accepted_with_its_fence_and_traceparent() -> None:
    service = FakeService()
    consumer = CommandConsumer("amqp://unused", "video-claude", service)  # type: ignore[arg-type]
    request = job_request()
    request["fence"] = 2
    await consumer.handle(envelope("job.requested", request))
    ((job, trace),) = service.accepted
    assert job.request.fence == 2 and trace == "00-aa-bb-01"


async def test_cancel_requested_cancels_the_job() -> None:
    service = FakeService()
    consumer = CommandConsumer("amqp://unused", "video-claude", service)  # type: ignore[arg-type]
    jid = uuid.uuid4()
    await consumer.handle(envelope("job.cancel_requested", {}, jid))
    assert service.cancelled == [jid]


@respx.mock
async def test_a_rejected_job_is_reported_to_the_core_with_the_fence() -> None:
    service = FakeService(ProblemError(422, "settings_invalid", "Settings snapshot is invalid"))
    consumer = CommandConsumer("amqp://unused", "video-claude", service, core_token="mft_x")  # type: ignore[arg-type]
    request = job_request()
    request["fence"] = 3
    base = request["callback"]["base_url"]
    route = respx.post(f"{base}/fail").mock(return_value=httpx.Response(200, json={}))
    await consumer.handle(envelope("job.requested", request))
    sent = route.calls.last.request
    assert sent.headers["x-fence"] == "3" and sent.headers["authorization"] == "Bearer mft_x"
    assert json.loads(sent.content)["details"]["code"] == "settings_invalid"


@pytest.fixture(scope="module")
def amqp_url(docker_client: Any) -> Iterator[str]:  # noqa: F811
    try:
        docker_client.images.get("rabbitmq:4-management")
    except Exception:
        pytest.skip("image rabbitmq:4-management is not present locally")
    box = docker_client.containers.run("rabbitmq:4-management", detach=True, ports={"5672/tcp": None})
    try:
        box.reload()
        port = box.attrs["NetworkSettings"]["Ports"]["5672/tcp"][0]["HostPort"]
        yield f"amqp://guest:guest@127.0.0.1:{port}/"
    finally:
        box.remove(force=True)


@pytest.mark.docker
async def test_a_core_style_job_command_reaches_the_module_queue(amqp_url: str) -> None:
    conn = await connect(amqp_url)
    try:
        channel = await conn.channel()
        await declare_command_queue(channel, "video-claude")
        await declare_command_queue(channel, "video-claude")  # idempotent: the core declares the same queue
        commands = await channel.get_exchange("manufacture.commands")
        msg = aio_pika.Message(envelope("job.requested", job_request()))
        await commands.publish(
            msg, routing_key="job.video.video-claude", mandatory=True
        )  # unroutable would raise
        queue = await channel.get_queue("module.video-claude.commands", ensure=False)
        got: list[Any] = []

        async def arrived() -> bool:
            m = await queue.get(fail=False)
            if m is not None:
                got.append(m)
                await m.ack()
            return bool(got)

        await wait_for(arrived)
    finally:
        await conn.close()
