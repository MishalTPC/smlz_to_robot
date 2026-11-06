"""Robot steel-section database matching (independent Python unit).

Identify section names in Robot's South African catalogues based on section
family and nominal dimensions. Never use unconstrained fuzzy/nearest matching.
The source sectionproperties results remain unchanged in the Excel workbook.

Autodesk Robot COM calls are isolated in ``get_database_sections`` and
``load_catalogue_section``. The name matcher runs without Robot/Windows.
"""
from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from robot_profile_names import profile_key as _profile_key, match_quality, nominal_chs_note

LOG = logging.getLogger(__name__)

# ZA = SAISC 2010 (South Africa); SADEF = SADEF steel sections.
DEFAULT_DATABASES = ("ZA", "SADEF")
# Match families and naming aliases using robot_profile_names.py.
# This isolates ZA/SADEF-specific aliases from Robot COM enumeration.

@dataclass(frozen=True)
class CatalogueEntry:
    database: str
    name: str


@dataclass(frozen=True)
class Match:
    source_name: str
    status: str  # matched, unmatched or ambiguous
    database: str | None = None
    catalogue_name: str | None = None
    candidates: tuple[str, ...] = ()
    reason: str = ""


def match_sections(
    source_name: str, catalogue: Iterable[CatalogueEntry],
    *, priority: tuple[str, ...] = DEFAULT_DATABASES,
    section_type: str = "", section_standard: str = "",
) -> Match:
    """Match a genuine catalogue profile by family and nominal dimensions.

    South African Robot names include AE (equal angle), AU (unequal angle),
    and CDIN (parallel-flange channel only). For CHS, a fractional SMLX
    outside diameter such as 101.6 mm may be catalogued as 102 mm.
    Exact matches take precedence over rounded-diameter matches.
    Ambiguous candidates are *never* selected arbitrarily.
    """
    target = _profile_key(
        source_name, section_type=section_type,
        section_standard=section_standard,
    )
    if target is None:
        return Match(
            source_name, "unmatched",
            reason="Unrecognised source family/nominal size or channel flange type",
        )
    entries = tuple((entry, _profile_key(entry.name)) for entry in catalogue)
    # Exact matching always takes priority, even if a rounded size is
    # available in a higher-priority database.
    for quality in ("exact", "rounded_chs"):
        for database in priority:
            hits = sorted({
                entry.name
                for entry, key in entries
                if entry.database.upper() == database.upper()
                and key is not None
                and match_quality(target, key) == quality
            })
            if len(hits) == 1:
                if quality == "rounded_chs":
                    name_key = _profile_key(hits[0])
                    assert name_key is not None
                    reason = nominal_chs_note(target, name_key)
                else:
                    reason = "Same section family and all nominal dimensions"
                return Match(
                    source_name, "matched", database,
                    hits[0], tuple(hits), reason,
                )
            if len(hits) > 1:
                return Match(
                    source_name, "ambiguous", database,
                    None, tuple(hits),
                    "Multiple catalogue profiles have the same family and nominal dimensions",
                )
    return Match(
        source_name, "unmatched",
        reason="No exact or permitted rounded-CHS family-and-size match in active databases",
    )


def get_database_sections(robot: object, constants: object,
                          database_names: tuple[str, ...] = DEFAULT_DATABASES
                          ) -> tuple[list[CatalogueEntry], dict[str, str]]:
    """Query each Robot section database through its COM NamesArray.

    The returned second dict records missing/inaccessible databases. Robot
    database names refer to catalogue codes, not filenames or Excel sections.
    """
    prefs = robot.Project.Preferences
    active = prefs.SectionsActive
    catalogue: list[CatalogueEntry] = []
    problems: dict[str, str] = {}

    def locate(code: str):
        for i in range(1, int(active.Count) + 1):
            database = active.GetDatabase(i)
            if str(database.Name).upper() == code.upper():
                return database
        return None

    for code in database_names:
        try:
            database = locate(code)
            if database is None:
                # Adding a database to the job preferences is necessary before
                # its contents can be enumerated or loaded into a section label.
                active.Add(code)
                database = locate(code)
            if database is None:
                problems[code] = "Database not available in this Robot installation"
                continue
            names = database.GetAll()
            for i in range(1, int(names.Count) + 1):
                candidate = str(names.Get(i)).strip()
                if candidate:
                    catalogue.append(CatalogueEntry(code, candidate))
        except Exception as exc:
            problems[code] = f"Robot catalogue enumeration failed: {exc}"
            LOG.warning("Could not enumerate Robot section database %s: %s", code, exc)
    return catalogue, problems


def load_catalogue_section(labels: object, constants: object, prefs: object,
                           label_name: str, material_name: str,
                           match: Match) -> dict[str, float]:
    """Load a genuine database section into a Robot bar-section label.

    Uses the documented LoadFromDBase2(profile, database) method and reads
    back basic mechanical values. The Robot catalogue values are NOT replaced
    with numerical values from sectionproperties.
    """
    if match.status != "matched" or not match.database or not match.catalogue_name:
        raise ValueError(f"Cannot load an unmatched Robot section: {match.source_name}")
    prefs.SetCurrentDatabase(constants.I_DT_SECTIONS, match.database)
    label = labels.Create(constants.I_LT_BAR_SECTION, label_name)
    data = label.Data
    data.LoadFromDBase2(match.catalogue_name, match.database)
    # Loading a catalogue can also set default steel material; override it
    # after the catalogue import, leaving the section geometry intact.
    data.MaterialName = material_name
    labels.Store(label)
    stored = labels.Get(constants.I_LT_BAR_SECTION, label_name).Data
    props = {}
    for key, enum in (
        ("A", "I_BSDV_AX"), ("Iy", "I_BSDV_IY"),
        ("Iz", "I_BSDV_IZ"), ("J", "I_BSDV_IX"),
    ):
        value = float(stored.GetValue(getattr(constants, enum)))
        if not math.isfinite(value) or value <= 0:
            raise RuntimeError(
                f"Catalogue section {label_name} returned an invalid {key}={value}"
            )
        props[key] = value
    return props


def compare_geometry(source_row: Any, robot_props: dict[str, float]) -> dict[str, float | None]:
    """Relative differences: catalogue/sectionproperties - 1, by property.

    A nonzero difference can be legitimate: catalogue fillets and effective
    dimensions may not appear in the exported SMLX polygon geometry.
    """
    result: dict[str, float | None] = {}
    for key in ("A", "Iy", "Iz", "J"):
        source = source_row[key] if isinstance(source_row, dict) else getattr(source_row, key)
        try:
            source_value = float(source)
        except (TypeError, ValueError):
            result[f"{key}_relative_difference"] = None
            continue
        if not math.isfinite(source_value) or source_value <= 0:
            result[f"{key}_relative_difference"] = None
        else:
            result[f"{key}_relative_difference"] = robot_props[key] / source_value - 1.0
    return result


def audit_record(property_id: int, match: Match, *, mode: str,
                 robot_props: dict[str, float] | None = None,
                 source_row: Any | None = None) -> dict[str, Any]:
    """Plain-JSON-safe provenance for the generated section assignment."""
    result: dict[str, Any] = {"property_id": property_id, **asdict(match), "assignment": mode}
    if robot_props is not None:
        result["robot_SI"] = robot_props
        if source_row is not None:
            result["relative_differences"] = compare_geometry(source_row, robot_props)
    return result