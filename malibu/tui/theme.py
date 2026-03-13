"""Theme constants for the Malibu TUI.

Defines the color palette, glyph sets (unicode with ASCII fallbacks),
and CSS variable names used throughout the interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ── Color Palette ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Colors:
    """Ocean-blue brand palette with semantic status colors."""

    # Brand — ocean blue gradient
    brand_primary: str = "#0077B6"
    brand_secondary: str = "#00B4D8"
    brand_accent: str = "#90E0EF"
    brand_dark: str = "#03045E"
    brand_light: str = "#CAF0F8"

    # Surface / background
    bg_primary: str = "#0A0E14"
    bg_secondary: str = "#11151C"
    bg_surface: str = "#1A1F2B"
    bg_elevated: str = "#232A38"

    # Text
    text_primary: str = "#E0E6ED"
    text_secondary: str = "#8892A0"
    text_muted: str = "#5C6370"
    text_inverse: str = "#0A0E14"

    # Status
    success: str = "#2ECC71"
    warning: str = "#F1C40F"
    error: str = "#E74C3C"
    info: str = "#00B4D8"

    # Borders
    border_default: str = "#2A3040"
    border_focus: str = "#0077B6"
    border_subtle: str = "#1E2430"


# ── Glyphs ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Glyphs:
    """Display glyphs with unicode and ASCII fallback variants."""

    checkmark: str = "\u2714"       # heavy check mark
    cross: str = "\u2718"           # heavy ballot X
    circle: str = "\u25CF"          # black circle
    circle_open: str = "\u25CB"     # white circle
    arrow_right: str = "\u25B6"     # right-pointing triangle
    arrow_down: str = "\u25BC"      # down-pointing triangle
    thinking: str = "\u2026"        # horizontal ellipsis
    separator: str = "\u2502"       # box-drawing vertical
    bullet: str = "\u2022"          # bullet
    branch: str = "\u251C"          # box-drawing tee right

    spinner_frames: tuple[str, ...] = (
        "\u280B", "\u2819", "\u2839", "\u2838",
        "\u283C", "\u2834", "\u2826", "\u2827",
        "\u2807", "\u280F",
    )

    @classmethod
    def ascii(cls) -> Glyphs:
        """Return an ASCII-safe glyph set for limited terminals."""
        return cls(
            checkmark="[x]",
            cross="[!]",
            circle="(*)",
            circle_open="( )",
            arrow_right=">",
            arrow_down="v",
            thinking="...",
            separator="|",
            bullet="*",
            branch="+-",
            spinner_frames=("-", "\\", "|", "/"),
        )


# ── CSS Variable Names ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class CSSVars:
    """Mapping of semantic names to Textual CSS variable identifiers.

    Use these when referencing ``$variable`` inside ``.tcss`` files or
    ``Widget.styles`` so names stay consistent across the codebase.
    """

    brand_primary: str = "brand-primary"
    brand_secondary: str = "brand-secondary"
    brand_accent: str = "brand-accent"
    brand_dark: str = "brand-dark"
    brand_light: str = "brand-light"

    bg_primary: str = "bg-primary"
    bg_secondary: str = "bg-secondary"
    bg_surface: str = "bg-surface"
    bg_elevated: str = "bg-elevated"

    text_primary: str = "text-primary"
    text_secondary: str = "text-secondary"
    text_muted: str = "text-muted"

    success: str = "success"
    warning: str = "warning"
    error: str = "error"
    info: str = "info"

    border_default: str = "border-default"
    border_focus: str = "border-focus"


# ── Singleton Defaults ───────────────────────────────────────────────────────

COLORS = Colors()
GLYPHS = Glyphs()
GLYPHS_ASCII = Glyphs.ascii()
CSS_VARS = CSSVars()
