"""Offline city lookup using the bundled GeoNames snapshot."""

import gzip
import json
import unicodedata
from importlib.resources import files
from typing import Protocol

from oria_engine.domain.birth_profile import BirthPlace


class PlaceResolver(Protocol):
    async def resolve(self, city: str, country: str) -> tuple[BirthPlace, ...]:
        """Return at most eight deterministic candidates; never use an LLM."""


class PlaceResolutionUnavailable(RuntimeError):
    """Local place data is not available; contains no query details."""


class TooManyPlaces(ValueError):
    """Ask for a region qualifier instead of silently hiding candidates."""


def normalized(value: str) -> str:
    return " ".join(
        "".join(
            c
            for c in unicodedata.normalize("NFKD", value.casefold())
            if not unicodedata.combining(c)
        ).split()
    )


class LocalPlaceResolver:
    def __init__(self) -> None:
        with files("oria_engine").joinpath("data/places.json.gz").open("rb") as source:
            data = json.loads(gzip.decompress(source.read()))
        self.countries: dict[str, str] = {}
        for code, names in data["countries"].items():
            for name in [code, *names]:
                self.countries[normalized(name)] = code
        self.countries.update({"uk": "GB", "usa": "US"})
        self.places: dict[int, BirthPlace] = {}
        self.index: dict[tuple[str, str], set[int]] = {}
        for row in data["places"]:
            place = BirthPlace.model_validate(row["place"])
            self.places[row["id"]] = place
            for name in row["names"]:
                key = (place.country_code, normalized(name))
                self.index.setdefault(key, set()).add(row["id"])

    async def resolve(self, city: str, country: str) -> tuple[BirthPlace, ...]:
        code = self.countries.get(normalized(country))
        if code is None:
            return ()
        name, separator, region = normalized(city).partition(" - ")
        candidates = [self.places[i] for i in sorted(self.index.get((code, name), ()))]
        if separator:
            candidates = [p for p in candidates if normalized(p.region or "") == region]
        if len(candidates) > 8:
            raise TooManyPlaces("Specify city - region, country")
        return tuple(candidates)


class UnavailablePlaceResolver:
    async def resolve(self, city: str, country: str) -> tuple[BirthPlace, ...]:
        raise PlaceResolutionUnavailable("Place lookup is not available yet")
