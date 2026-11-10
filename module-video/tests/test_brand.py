from mvideo.brand import brand_palette, with_brand


def test_kafka_repository_gets_the_kafka_palette() -> None:
    analysis = {"system": {"repo": "https://github.com/apache/kafka"}}
    assert brand_palette(analysis)["accent"] == "#231F20"
    values = with_brand({"palette": {"page": "#000000", "keep": "#123456"}}, analysis)
    assert values["palette"]["page"] == "#FFFFFF"
    assert values["palette"]["keep"] == "#123456"


def test_other_systems_keep_the_channel_palette() -> None:
    analysis = {"system": {"repo": "https://git.postgresql.org/git/postgresql.git"}}
    assert brand_palette(analysis) == {}
    values = {"palette": {"accent": "#FF6B00"}}
    assert with_brand(values, analysis) == {"palette": {"accent": "#FF6B00"}}
