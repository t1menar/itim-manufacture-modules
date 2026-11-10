from publish.storage.artifacts import shorten_caption

LONG = (
    "A Kafka topic is just a folder of files: one directory per partition.\n\n"
    + "\n".join(f"{i}. step number {i} " + "x" * 80 for i in range(1, 8))
    + "\n\nSource: github.com/apache/kafka · 4.4.0"
)


def test_long_caption_keeps_hook_source_and_whole_lines() -> None:
    out = shorten_caption(LONG, 500)
    assert len(out) <= 500
    assert out.startswith("A Kafka topic is just a folder")
    assert out.endswith("Source: github.com/apache/kafka · 4.4.0")
    assert all(ln.startswith(("A Kafka", "Source")) or ln[0].isdigit() for ln in out.split("\n") if ln.strip())


def test_short_caption_is_untouched() -> None:
    assert shorten_caption("short one") == "short one"
