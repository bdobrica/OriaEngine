"""Single-process deterministic Swiss Ephemeris adapter; no persistence or network."""

import os
from importlib.metadata import version
from itertools import combinations
from threading import Lock

import swisseph as swe

from oria_engine.astrology.contracts import (
    Angles,
    Aspect,
    Availability,
    Body,
    CalculationMetadata,
    NatalRequest,
    NatalResult,
    Planet,
)

LOCK = Lock()
BODIES: tuple[Body, ...] = (
    "sun",
    "moon",
    "mercury",
    "venus",
    "mars",
    "jupiter",
    "saturn",
    "uranus",
    "neptune",
    "pluto",
)
SIGNS = (
    "Aries",
    "Taurus",
    "Gemini",
    "Cancer",
    "Leo",
    "Virgo",
    "Libra",
    "Scorpio",
    "Sagittarius",
    "Capricorn",
    "Aquarius",
    "Pisces",
)
TARGETS = (("conjunction", 0), ("sextile", 60), ("square", 90), ("trine", 120), ("opposition", 180))
FLAGS = swe.FLG_MOSEPH | swe.FLG_SPEED


class CalculationUnavailable(RuntimeError):
    """Payload-free failure; do not return underlying library diagnostics."""


def metadata() -> CalculationMetadata:
    if os.environ.get("SE_EPHE_PATH"):
        raise CalculationUnavailable("External ephemeris configuration is unsupported")
    if version("pyswisseph") != "2.10.3.2" or swe.version != "2.10.03":
        raise CalculationUnavailable("Calculation dependency version mismatch")
    return CalculationMetadata(swiss_ephemeris_version=swe.version)


def aspects(planets: tuple[Planet, ...]) -> tuple[Aspect, ...]:
    results = []
    for a, b in combinations(planets, 2):
        signed = (b.longitude - a.longitude + 180) % 360 - 180
        separation = abs(signed)
        relative = b.longitude_velocity_deg_day - a.longitude_velocity_deg_day
        separation_speed = relative if signed >= 0 else -relative
        for name, target in TARGETS:
            error = separation - target
            if abs(error) <= 6:
                # At exactness, station, or a separation cusp, motion is indeterminate.
                applying = (
                    None
                    if min(abs(error), abs(relative), separation, abs(180 - separation)) < 1e-8
                    else error * separation_speed < 0
                )
                results.append(
                    Aspect.model_validate(
                        dict(
                            body_a=a.body,
                            body_b=b.body,
                            name=name,
                            target_angle=target,
                            angular_separation=separation,
                            orb=abs(error),
                            relative_velocity_deg_day=relative,
                            applying=applying,
                        )
                    )
                )
    return tuple(results)


def house_for(longitude: float, cusps: tuple[float, ...]) -> int | None:
    for i, start in enumerate(cusps):
        end = cusps[(i + 1) % 12]
        if (longitude - start) % 360 < (end - start) % 360:
            return i + 1
    return None


def calculate(request: NatalRequest) -> NatalResult:
    request = NatalRequest.model_validate(request)
    meta = metadata()
    if request.birth_time_accuracy == "unknown":
        return NatalResult(
            birth_time_accuracy="unknown",
            planets=(),
            angles=None,
            house_cusps=(),
            aspects=(),
            availability=Availability(
                positions=False,
                houses=False,
                angles=False,
                aspects=False,
                reasons=("unknown_birth_time",),
            ),
            metadata=meta,
        )
    assert request.timestamp_utc is not None
    instant = request.timestamp_utc
    try:
        with LOCK:
            # No external files; reset process-global ephemeris settings before each request.
            swe.set_ephe_path("/nonexistent/oria-ephemeris")
            swe.set_tid_acc(swe.TIDAL_MOSEPH)
            swe.set_delta_t_userdef(swe.DELTAT_AUTOMATIC)
            tt, ut = swe.utc_to_jd(
                instant.year,
                instant.month,
                instant.day,
                instant.hour,
                instant.minute,
                instant.second + instant.microsecond / 1e6,
                swe.GREG_CAL,
            )
            raw = []
            for index, body in enumerate(BODIES):
                values, flags = swe.calc(tt, index, FLAGS)
                if flags & (swe.FLG_MOSEPH | swe.FLG_SWIEPH | swe.FLG_JPLEPH) != swe.FLG_MOSEPH:
                    raise CalculationUnavailable("Unexpected ephemeris backend")
                raw.append((body, values))
            cusps: tuple[float, ...] = ()
            angles = None
            # Placidus is intentionally unsupported at/above 66 degrees in v1.
            if abs(request.latitude) < 66:
                try:
                    calculated_cusps, axes = swe.houses_ex(
                        ut, request.latitude, request.longitude, b"P"
                    )
                    cusps = tuple(calculated_cusps)
                    angles = Angles(ascendant=axes[0], midheaven=axes[1])
                except swe.Error:
                    pass
            planets = tuple(
                Planet.model_validate(
                    dict(
                        body=body,
                        longitude=values[0] % 360,
                        sign=SIGNS[int(values[0] % 360 // 30)],
                        degree_in_sign=values[0] % 30,
                        longitude_velocity_deg_day=values[3],
                        retrograde=values[3] < 0,
                        house=house_for(values[0], cusps),
                    )
                )
                for body, values in raw
            )
        reasons = []
        if request.birth_time_accuracy == "approximate":
            reasons.append("approximate_birth_time")
        if not cusps:
            reasons.append("houses_unsupported")
        return NatalResult(
            birth_time_accuracy=request.birth_time_accuracy,
            planets=planets,
            angles=angles,
            house_cusps=cusps,
            aspects=aspects(planets),
            metadata=meta,
            availability=Availability.model_validate(
                dict(
                    positions=True,
                    houses=bool(cusps),
                    angles=angles is not None,
                    aspects=True,
                    reasons=reasons,
                )
            ),
        )
    except Exception:
        raise CalculationUnavailable("Natal calculation unavailable") from None
