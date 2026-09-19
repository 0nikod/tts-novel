from __future__ import annotations

from ..models import Style
from .models import CompiledStyle


def compile_style(provider: str, text: str, style: Style | None) -> CompiledStyle:
    """Compile the small provider-neutral style shape at the provider boundary."""
    if not style:
        return CompiledStyle(text=text)

    values = {
        field: list(value) if isinstance(value, list) else value for field, value in style.items()
    }
    direction = style.get("direction")
    instruction = direction if isinstance(direction, str) else None
    if provider != "mimo":
        return CompiledStyle(text=text, instruction=instruction, values=values)

    rendered_text = text
    before = _tag_group(style.get("tags_before"))
    after = _tag_group(style.get("tags_after"))
    if before:
        rendered_text = f"（{before}）{rendered_text}"
    if after:
        rendered_text = f"{rendered_text}（{after}）"
    return CompiledStyle(
        text=rendered_text,
        instruction=instruction,
        values=values,
    )


def _tag_group(value: str | list[str] | None) -> str | None:
    if not isinstance(value, list) or not value:
        return None
    return "｜".join(value)
