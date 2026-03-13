"""Controller for mirroring input completions into the popup widget."""

from __future__ import annotations

from malibu.tui.widgets.autocomplete_popup import AutocompletePopup


class AutocompletePopupController:
    """Update the popup when the input emits completion changes."""

    def __init__(self, popup: AutocompletePopup) -> None:
        self.popup = popup

    def update(self, items: list[tuple[str, str]], selected: int | None) -> None:
        self.popup.update_items(items, selected)
