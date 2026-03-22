from __future__ import annotations

import malibu
import vibe
from malibu.core.config import VibeConfig


def test_malibu_namespace_reexports_vibe_package() -> None:
    assert malibu.__version__ == vibe.__version__
    assert malibu.MALIBU_ROOT == vibe.VIBE_ROOT
    assert VibeConfig is not None
