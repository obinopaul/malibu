"""Content block conversion — ACP ↔ LangChain multimodal formats.

Mirrors the full set of ACP content block types:
  TextContentBlock, ImageContentBlock, AudioContentBlock,
  ResourceContentBlock, EmbeddedResourceContentBlock
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from acp.schema import (
        AudioContentBlock,
        EmbeddedResourceContentBlock,
        ImageContentBlock,
        ResourceContentBlock,
        TextContentBlock,
    )


def convert_text_block(block: TextContentBlock) -> list[dict[str, str]]:
    """ACP TextContentBlock → LangChain content dicts."""
    return [{"type": "text", "text": block.text}]


def convert_image_block(block: ImageContentBlock) -> list[dict[str, object]]:
    """ACP ImageContentBlock → LangChain image_url content dict."""
    if block.data:
        data_uri = f"data:{block.mime_type};base64,{block.data}"
        return [{"type": "image_url", "image_url": {"url": data_uri}}]
    if block.uri:
        return [{"type": "image_url", "image_url": {"url": block.uri}}]
    return [{"type": "text", "text": "[Image: no data available]"}]


def convert_audio_block(block: AudioContentBlock) -> list[dict[str, str]]:
    """ACP AudioContentBlock → LangChain content dict (raises for now)."""
    raise NotImplementedError("Audio content blocks are not yet supported")


def convert_resource_block(block: ResourceContentBlock, *, root_dir: str) -> list[dict[str, str]]:
    """ACP ResourceContentBlock (link) → LangChain text description."""
    file_prefix = "file://"
    parts = [f"[Resource: {block.name}"]
    if block.uri:
        uri = block.uri
        has_prefix = uri.startswith(file_prefix)
        path = uri[len(file_prefix):] if has_prefix else uri
        if path.startswith(root_dir):
            path = path[len(root_dir):].lstrip("/")
        uri = f"file://{path}" if has_prefix else path
        parts.append(f"\nURI: {uri}")
    if block.description:
        parts.append(f"\nDescription: {block.description}")
    if block.mime_type:
        parts.append(f"\nMIME type: {block.mime_type}")
    parts.append("]")
    return [{"type": "text", "text": "".join(parts)}]


def convert_embedded_resource_block(block: EmbeddedResourceContentBlock) -> list[dict[str, str]]:
    """ACP EmbeddedResourceContentBlock → LangChain text/blob content dict."""
    resource = block.resource
    if hasattr(resource, "text"):
        mime_type = getattr(resource, "mime_type", "text/plain")
        return [{"type": "text", "text": f"[Embedded {mime_type} resource: {resource.text}]"}]
    if hasattr(resource, "blob"):
        mime_type = getattr(resource, "mime_type", "application/octet-stream")
        data_uri = f"data:{mime_type};base64,{resource.blob}"
        return [{"type": "text", "text": f"[Embedded resource: {data_uri}]"}]
    raise ValueError("Embedded resource block must have either 'text' or 'blob'")


def convert_any_block(block, *, root_dir: str = "") -> list[dict[str, str]]:
    """Dispatch to the appropriate converter based on block type."""
    from acp.schema import (
        AudioContentBlock,
        EmbeddedResourceContentBlock,
        ImageContentBlock,
        ResourceContentBlock,
        TextContentBlock,
    )

    if isinstance(block, TextContentBlock):
        return convert_text_block(block)
    if isinstance(block, ImageContentBlock):
        return convert_image_block(block)
    if isinstance(block, AudioContentBlock):
        return convert_audio_block(block)
    if isinstance(block, ResourceContentBlock):
        return convert_resource_block(block, root_dir=root_dir)
    if isinstance(block, EmbeddedResourceContentBlock):
        return convert_embedded_resource_block(block)
    return [{"type": "text", "text": str(block)}]
