from pathlib import Path

from internal.core.protocol.image_output_paths import (
    ImagePathStreamNormalizer,
    enforce_absolute_image_paths,
)


def test_enforce_absolute_image_paths_local_relative(tmp_path: Path):
    text = "done ![img](artifacts/plot.png) ok"
    out = enforce_absolute_image_paths(text, base_dir=tmp_path)
    assert "![img](" in out
    assert f"{tmp_path.as_posix()}/artifacts/plot.png" in out


def test_enforce_absolute_image_paths_keep_remote_and_data():
    text = "![a](https://example.com/a.png) ![b](data:image/png;base64,abc)"
    out = enforce_absolute_image_paths(text)
    assert "https://example.com/a.png" in out
    assert "data:image/png;base64,abc" in out


def test_stream_normalizer_handles_split_markdown(tmp_path: Path):
    norm = ImagePathStreamNormalizer(base_dir=tmp_path, keep_tail=32)
    p1 = norm.feed("before ![img](arti")
    p2 = norm.feed("facts/plot.png) after")
    p3 = norm.flush()
    merged = p1 + p2 + p3
    assert f"{tmp_path.as_posix()}/artifacts/plot.png" in merged
