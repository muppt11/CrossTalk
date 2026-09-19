from pathlib import Path
from typing import Any

import streamlit as st


_ASSET_DIR = Path(__file__).parent
_JS = (_ASSET_DIR / "card_selector.js").read_text(encoding="utf-8")
_CSS = (_ASSET_DIR / "card_selector.css").read_text(encoding="utf-8")

_render_card_selector = st.components.v2.component(
    "card_selector",
    html='<div class="card-selector-root"></div>',
    css=_CSS,
    js=_JS,
)


def card_selector(items: list[dict[str, Any]], key: str | None = None) -> list[str]:
    """Render a horizontally-scrollable card strip; returns the selected `full_name`s."""
    result = _render_card_selector(
        data={"items": items},
        default={"selected": []},
        on_selected_change=lambda: None,
        key=key,
    )
    return result.selected
