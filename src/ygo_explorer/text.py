"""Text normalization shared by the loader and the query layer."""

from __future__ import annotations

import unicodedata

__all__ = ["fold"]


def fold(value: str) -> str:
    """Fold text for diacritic- and case-insensitive comparison.

    Decomposes with NFKD, drops combining marks, then casefolds, so
    ``Necrovalley`` and ``Nécrovalley`` compare equal. Both sides of a
    comparison must go through this one function — never fold inline at a
    call site, or the two sides drift apart.
    """
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return without_marks.casefold()
