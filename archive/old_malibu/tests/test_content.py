"""Tests for malibu.server.content module."""

from __future__ import annotations

import pytest
from acp.schema import AudioContentBlock, ImageContentBlock, TextContentBlock

from malibu.server.content import (
    convert_any_block,
    convert_audio_block,
    convert_image_block,
    convert_text_block,
)


def test_convert_text_block():
    block = TextContentBlock(type="text", text="hello")
    result = convert_text_block(block)
    assert result == [{"type": "text", "text": "hello"}]


def test_convert_image_block_data():
    block = ImageContentBlock(type="image", data="base64data", mime_type="image/png")
    result = convert_image_block(block)
    assert len(result) == 1
    assert result[0]["type"] == "image_url"
    assert "base64data" in result[0]["image_url"]["url"]


def test_convert_image_block_uri():
    block = ImageContentBlock(type="image", data="", uri="https://example.com/img.png", mime_type="image/png")
    result = convert_image_block(block)
    assert result[0]["image_url"]["url"] == "https://example.com/img.png"


def test_convert_audio_block_not_implemented():
    block = AudioContentBlock(type="audio", data="audiodata", mime_type="audio/wav")
    with pytest.raises(NotImplementedError):
        convert_audio_block(block)


def test_convert_any_block_text():
    block = TextContentBlock(type="text", text="hello")
    result = convert_any_block(block)
    assert result == [{"type": "text", "text": "hello"}]


def test_convert_any_block_image():
    block = ImageContentBlock(type="image", data="b64", mime_type="image/png")
    result = convert_any_block(block)
    assert result[0]["type"] == "image_url"


def test_convert_any_block_unknown():
    """Unknown object types should be stringified."""
    result = convert_any_block("just a string")
    assert result == [{"type": "text", "text": "just a string"}]
