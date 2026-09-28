"""Generate bundled public place/timezone data from local upstream snapshots.

Usage: python scripts/import_places.py SOURCE_DIRECTORY ZONEINFO_DIRECTORY
SOURCE_DIRECTORY contains cities15000.zip, countryInfo.txt, admin1CodesASCII.txt.
No user data or network calls. See docs/place-resolution.md before refreshing.
"""

import gzip
import hashlib
import json
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


def generate(source: Path, zoneinfo: Path, output: Path) -> None:
    countries = {}
    for line in (source / "countryInfo.txt").read_text().splitlines():
        if line and not line.startswith("#"):
            row = line.split("\t")
            countries[row[0]] = [row[1], row[4]]
    regions = {}
    for line in (source / "admin1CodesASCII.txt").read_text().splitlines():
        row = line.split("\t")
        regions[row[0]] = row[1]
    places = []
    zones = set()
    with ZipFile(source / "cities15000.zip") as archive:
        for line in archive.read("cities15000.txt").decode().splitlines():
            row = line.split("\t")
            if not row[17]:
                raise ValueError("City without timezone")
            zones.add(row[17])
            places.append(
                {
                    "id": int(row[0]),
                    "names": sorted(set([row[1], row[2], *row[3].split(",")]) - {""}),
                    "place": {
                        "display_name": row[1],
                        "city": row[1],
                        "region": regions.get(f"{row[8]}.{row[10]}"),
                        "country_code": row[8],
                        "latitude": float(row[4]),
                        "longitude": float(row[5]),
                        "timezone": row[17],
                    },
                }
            )
    output.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {"countries": countries, "places": sorted(places, key=lambda p: p["id"])},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    (output / "places.json.gz").write_bytes(gzip.compress(payload, mtime=0))
    # Include all TZif files, including aliases, to keep existing normalized profiles readable.
    with ZipFile(output / "timezones.zip", "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(zoneinfo.rglob("*")):
            name = path.relative_to(zoneinfo).as_posix()
            if path.is_file() and not name.startswith(("posix/", "right/")):
                data = path.read_bytes()
                if data.startswith(b"TZif") and name not in {"localtime", "posixrules"}:
                    archive.writestr(ZipInfo(name), data, compress_type=ZIP_DEFLATED)
    with ZipFile(output / "timezones.zip") as archive:
        assert zones <= set(archive.namelist())
    inputs = [source / n for n in ("cities15000.zip", "countryInfo.txt", "admin1CodesASCII.txt")]
    manifest = {
        "source": "https://download.geonames.org/export/dump/",
        "license": "https://creativecommons.org/licenses/by/4.0/",
        "city_count": len(places),
        "tzdata": (zoneinfo / "tzdata.zi").read_text().splitlines()[0],
        "sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
        "outputs_sha256": {
            n: hashlib.sha256((output / n).read_bytes()).hexdigest()
            for n in ("places.json.gz", "timezones.zip")
        },
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    generate(Path(sys.argv[1]), Path(sys.argv[2]), Path("src/oria_engine/data"))
