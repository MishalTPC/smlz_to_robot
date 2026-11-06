"""Conservative Robot steel-profile name normalisation.

The source SMLX workbook is not changed. Nomenclature here reflects the
South African Robot profile names observed by the user:
AE = equal angle, AU = unequal angle, CDIN = parallel-flange channel.

Only the *outer diameter* of CHS profiles may be rounded to the nearest
whole millimetre in the catalogue, and only after exact matches have failed.
Actual Robot section geometry/properties still need COM readback checks.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

# Longest alternatives first. Single-letter C cannot imply a parallel channel
# unless the source metadata expressly identifies a parallel-flange family.
_FAMILY = re.compile(
    r"(?<![A-Z])(CDIN|CHS|RPA|PFC|UPN|UB|UC|AE|AU|EA|UA|RO|RK|L|C)(?![A-Z])",
    re.IGNORECASE,
)
_NUMBERS = re.compile(r"(?<![\d.])\d+(?:\.\d+)?")

# Source and catalogue aliases, mapped into mechanical-profile families.
_BASE_FAMILY = {
    "CHS": "CHS", "RO": "CHS", "RK": "CHS", "RPA": "CHS",
    "UB": "UB", "UC": "UC",
    "AE": "AE", "EA": "AE", "AU": "AU", "UA": "AU",
    "PFC": "PFC", "CDIN": "PFC",
}


def profile_key(name: str, *, section_type: str = "", section_standard: str = "") -> tuple[str, tuple[Decimal, ...]] | None:
    """Return (family, complete exact nominal dimensions) or None.

    Equal and unequal L angles are distinguished from their leg dimensions.
    CDIN is deliberately *not* matched to UPN or arbitrary C-sections.
    The source context is used only when interpreting an ambiguous 'C'.
    """
    s = (str(name).upper().replace("×", "X").replace("*", "X")
         .replace("Ø", "").replace(",", "."))
    found = _FAMILY.findall(s)
    if len(found) != 1:
        return None
    code = found[0].upper()
    if code == "UPN":
        return None  # Sloping flange channels are never treated as CDIN.
    without = _FAMILY.sub(" ", s, count=1)
    parts = _NUMBERS.findall(without)
    expected_count = 2 if code in ("CHS", "RO", "RK", "RPA") else 3
    if len(parts) != expected_count:
        return None
    try:
        sizes = tuple(Decimal(v).normalize() for v in parts)
    except InvalidOperation:
        return None
    if any(v <= 0 for v in sizes):
        return None

    if code == "L":
        family = "AE" if sizes[0] == sizes[1] else "AU"
    elif code == "C":
        context = f"{section_type} {section_standard}".upper()
        # Do not infer this is a parallel-flange channel merely from 'C'.
        if not ("PFC" in context or "PARALLEL" in context):
            return None
        family = "PFC"
    else:
        family = _BASE_FAMILY.get(code)
        if family is None:
            return None
    if family == "AE" and sizes[0] != sizes[1]:
        return None
    if family == "AU" and sizes[0] == sizes[1]:
        return None
    return family, sizes


def match_quality(source_key: tuple[str, tuple[Decimal, ...]],
                  catalogue_key: tuple[str, tuple[Decimal, ...]]) -> str | None:
    """Return 'exact', 'rounded_chs', or None; never use nearest-neighbour."""
    source_family, source_size = source_key
    cat_family, cat_size = catalogue_key
    if source_family != cat_family:
        return None
    if source_size == cat_size:
        return "exact"
    if source_family != "CHS" or len(source_size) != 2 or len(cat_size) != 2:
        return None
    # No rounding for wall thickness. CHS outer diameter may round to the
    # *nearest whole millimetre* as used by Robot's nominal designation.
    d_source, t_source = source_size
    d_cat, t_cat = cat_size
    if t_source != t_cat or d_cat != d_cat.to_integral_value():
        return None
    rounded_d = d_source.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if d_cat != rounded_d or abs(d_cat - d_source) > Decimal("0.5"):
        return None
    return "rounded_chs"


def nominal_chs_note(source_key: tuple[str, tuple[Decimal, ...]],
                     catalogue_key: tuple[str, tuple[Decimal, ...]]) -> str:
    source_d = source_key[1][0]
    catalogue_d = catalogue_key[1][0]
    return (f"Rounded CHS nominal outside diameter {source_d} mm to "
            f"{catalogue_d} mm; wall thickness matched exactly. "
            "Robot properties must be checked against the original SMLX dimensions.")