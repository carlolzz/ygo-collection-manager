"""The provider protocol every price source implements."""

from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable

from ..money import Money

__all__ = ["PriceProvider", "PriceKey", "CredentialsRequired", "ProviderError"]

#: (passcode, set_code). set_code is None when the row has no printing — that is
#: a valid key, not a missing one, and must return a per-passcode price.
PriceKey = tuple[str, str | None]


class ProviderError(RuntimeError):
    """A provider could not answer."""


class CredentialsRequired(ProviderError):
    """The provider needs credentials that have not been supplied."""


@runtime_checkable
class PriceProvider(Protocol):
    """A source of prices.

    ``prices`` is not batch sugar over ``price``: the YGOPRODeck provider is
    dump-backed, so a one-at-a-time interface would be an actively misleading
    shape for it, and the whole-collection path only makes sense in batch.
    Implementations should make ``prices`` the real method.
    """

    name: str
    currency: str
    source_field: str

    def price(self, passcode: str, set_code: str | None = None) -> Money | None: ...

    def prices(self, keys: Sequence[PriceKey]) -> dict[PriceKey, Money | None]: ...
