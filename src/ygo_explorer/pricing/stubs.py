"""Providers that need credentials nobody has yet.

Present so the pluggable shape is real rather than aspirational, and so the UI
can list them as unavailable with an accurate reason instead of pretending they
do not exist.
"""

from __future__ import annotations

from typing import Sequence

from ..money import Money
from .provider import CredentialsRequired, PriceKey

__all__ = ["CardmarketProvider", "TcgplayerProvider"]


class CardmarketProvider:
    """Cardmarket. EUR, and the market this collection is actually bought in.

    Their API requires a registered app and OAuth 1.0a, granted on request.
    """

    name = "cardmarket"
    currency = "EUR"
    source_field = "cardmarket_api"

    _WHY = (
        "The Cardmarket provider needs credentials: a registered app and OAuth "
        "tokens, granted on request. Set CARDMARKET_APP_TOKEN / _APP_SECRET / "
        "_ACCESS_TOKEN / _ACCESS_SECRET once you have them."
    )

    def price(self, passcode: str, set_code: str | None = None) -> Money | None:
        raise CredentialsRequired(self._WHY)

    def prices(self, keys: Sequence[PriceKey]) -> dict[PriceKey, Money | None]:
        raise CredentialsRequired(self._WHY)


class TcgplayerProvider:
    """TCGplayer. USD.

    Public API access has been partner-gated for some time; check the current
    state before building against it rather than assuming this stub is still an
    accurate description.
    """

    name = "tcgplayer"
    currency = "USD"
    source_field = "tcgplayer_api"

    _WHY = (
        "The TCGplayer provider needs credentials, and public API access has "
        "been partner-gated. Confirm the current access model before "
        "implementing this."
    )

    def price(self, passcode: str, set_code: str | None = None) -> Money | None:
        raise CredentialsRequired(self._WHY)

    def prices(self, keys: Sequence[PriceKey]) -> dict[PriceKey, Money | None]:
        raise CredentialsRequired(self._WHY)
