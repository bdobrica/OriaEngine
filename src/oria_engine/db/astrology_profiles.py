"""Consent-scoped derived cache. Caller holds the transaction through calculation."""

import asyncio
import json
from functools import lru_cache
from importlib.resources import files
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from oria_engine.astrology.client import AstrologyClient, AstrologyUnavailable
from oria_engine.astrology.contracts import CalculationMetadata, NatalRequest, NatalResult
from oria_engine.db.birth_profiles import BirthProfileRepository, ConsentRequiredError
from oria_engine.db.models import AstrologyProfile, BirthProfile, OnboardingProgress, User
from oria_engine.db.repositories import ConsentRepository, UserRepository, UserUnavailableError


@lru_cache(maxsize=1)
def calculation_versions() -> dict[str, Any]:
    manifest = json.loads(files("oria_engine").joinpath("data/manifest.json").read_text())
    return {
        "contract_version": 1,
        **CalculationMetadata().model_dump(mode="json"),
        "timezone_version": manifest["tzdata"],
        "dataset_hashes": manifest["outputs_sha256"],
    }


class AstrologyProfileRepository:
    def __init__(self, session: AsyncSession, *, policy_version: str) -> None:
        self.session = session
        self.policy_version = policy_version

    async def invalidate(self, user_id: UUID) -> None:
        if await UserRepository(self.session).get(user_id, for_update=True) is None:
            raise UserUnavailableError("User unavailable")
        await self.session.execute(
            delete(AstrologyProfile).where(AstrologyProfile.user_id == user_id)
        )

    async def get(self, user_id: UUID) -> NatalResult | None:
        if await ConsentRepository(self.session).current(user_id, self.policy_version) is None:
            return None
        row = await self.session.scalar(
            select(AstrologyProfile)
            .join(User, User.id == AstrologyProfile.user_id)
            .join(BirthProfile, BirthProfile.id == AstrologyProfile.source_profile_id)
            .where(
                AstrologyProfile.user_id == user_id,
                BirthProfile.user_id == user_id,
                User.deleted_at.is_(None),
                AstrologyProfile.source_updated_at == BirthProfile.updated_at,
                AstrologyProfile.source_schema_version == BirthProfile.schema_version,
                ~select(OnboardingProgress.user_id)
                .where(OnboardingProgress.user_id == user_id)
                .exists(),
            )
            .execution_options(populate_existing=True)
        )
        if row is None or row.calculation_versions != calculation_versions():
            return None
        try:
            return NatalResult.model_validate(row.result)
        except ValidationError:
            return None

    async def calculate(
        self, user_id: UUID, profiles: BirthProfileRepository, client: AstrologyClient
    ) -> NatalResult:
        if await UserRepository(self.session).get(user_id, for_update=True) is None:
            raise UserUnavailableError("User unavailable")
        if await ConsentRepository(self.session).current(user_id, self.policy_version) is None:
            raise ConsentRequiredError("Current consent required")
        if await self.session.get(OnboardingProgress, user_id) is not None:
            raise AstrologyUnavailable("Profile confirmation required")
        cached = await self.get(user_id)
        if cached is not None:
            return cached
        payload = await profiles.get(user_id)
        source = await self.session.scalar(
            select(BirthProfile).where(BirthProfile.user_id == user_id)
        )
        if payload is None or source is None:
            raise AstrologyUnavailable("Confirmed profile required")
        instant = payload.utc_instant()
        try:
            request = NatalRequest(
                timestamp_utc=instant,
                local_birth_date=payload.birth_date if instant is None else None,
                birth_time_accuracy=payload.birth_time_accuracy,
                latitude=payload.birth_place.latitude,
                longitude=payload.birth_place.longitude,
            )
        except ValueError:
            raise AstrologyUnavailable("Birth date is outside calculation support") from None
        try:
            async with asyncio.timeout(20):
                result = NatalResult.model_validate(await client.calculate_natal_chart(request))
            if result.birth_time_accuracy != request.birth_time_accuracy:
                raise AstrologyUnavailable()
        except Exception:
            raise AstrologyUnavailable("Chart calculation temporarily unavailable") from None
        await self.invalidate(user_id)
        self.session.add(
            AstrologyProfile(
                user_id=user_id,
                source_profile_id=source.id,
                source_updated_at=source.updated_at,
                source_schema_version=source.schema_version,
                calculation_versions=calculation_versions(),
                result=result.model_dump(mode="json"),
            )
        )
        await self.session.flush()
        return result
