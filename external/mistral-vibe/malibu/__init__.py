from __future__ import annotations

from pathlib import Path

import vibe as _vibe

VIBE_ROOT = _vibe.VIBE_ROOT
MALIBU_ROOT = Path(VIBE_ROOT)
__version__ = _vibe.__version__
__path__ = list(_vibe.__path__)
