from pathlib import Path

import streamlit as st


_ASSET_DIR = Path(__file__).parent
_JS = (_ASSET_DIR / "text_morph.js").read_text(encoding="utf-8")
_CSS = (_ASSET_DIR / "text_morph.css").read_text(encoding="utf-8")

_render_text_morph = st.components.v2.component(
    "text_morph",
    html='<span class="text-morph-root"></span>',
    css=_CSS,
    js=_JS,
)


def text_morph(words: list[str], interval: int = 2600, morph_duration: int = 680, key: str | None = None) -> None:
    """Render componentry.dev's Text Morph effect, cycling through `words` in place."""
    _render_text_morph(
        data={"words": words, "interval": interval, "morphDuration": morph_duration},
        key=key,
    )
