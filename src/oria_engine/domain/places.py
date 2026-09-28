"""Local resolver boundary; the gazetteer implementation belongs to Stage 8."""

from typing import Protocol

from oria_engine.domain.birth_profile import BirthPlace


class PlaceResolver(Protocol):
    async def resolve(self, city: str, country: str) -> tuple[BirthPlace, ...]:
        """Return at most eight deterministic candidates; never use an LLM."""


class PlaceResolutionUnavailable(RuntimeError):
    """Local place data is not available; contains no query details."""


class UnavailablePlaceResolver:
    async def resolve(self, city: str, country: str) -> tuple[BirthPlace, ...]:
        raise PlaceResolutionUnavailable("Place lookup is not available yet")
