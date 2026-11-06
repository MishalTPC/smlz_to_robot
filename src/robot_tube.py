"""Create and verify rendered circular hollow sections in Autodesk Robot.

Robot's parametric tube section is *not* the same as a generic numerical
section label: the former carries outside diameter and wall thickness so
Robot can render the physical tube outline. COM is injected by the caller;
this unit also runs under offline fakes without Autodesk or Windows.

All input/output geometric quantities use SI units (metres, m², m⁴).
"""
from __future__ import annotations

import math
from typing import Any


def expected_annulus_properties(diameter_m: float, thickness_m: float) -> dict[str, float]:
    """Exact circular hollow-section properties for an ideal sharp-edged annulus."""
    d = float(diameter_m)
    t = float(thickness_m)
    if not math.isfinite(d) or not math.isfinite(t) or d <= 0 or t <= 0 or t >= d / 2:
        raise ValueError(
            "CHS outside diameter and thickness must be finite, positive, "
            "and satisfy 0 < thickness < diameter/2"
        )
    inside = d - 2.0 * t
    area = math.pi / 4 * (d * d - inside * inside)
    inertia = math.pi / 64 * (d**4 - inside**4)
    return {"A": area, "Iy": inertia, "Iz": inertia, "J": 2.0 * inertia}


def is_chs(section_row: Any) -> bool:
    """Identify a CHS using section type (preferred) or the source designation."""
    kind = str(getattr(section_row, "section_type", "")).strip().upper()
    name = str(getattr(section_row, "section_name", "")).strip().upper()
    return kind == "CHS" or name.startswith("CHS")


def chs_dimensions(section_row: Any) -> tuple[float, float]:
    """Read CHS outside diameter and thickness from *Excel* columns, not its name."""
    d = float(section_row.h)
    t = float(section_row.t)
    # The imported circular section has both outer dimensions equal to D.
    # Reject conflicting dimensions rather than choosing the wrong shape.
    try:
        b = float(section_row.b)
    except (ValueError, TypeError, AttributeError):
        b = math.nan
    if math.isfinite(b) and not math.isclose(b, d, rel_tol=2e-4, abs_tol=2e-7):
        raise ValueError(f"CHS {section_row.section_name}: h={d} and b={b} are inconsistent")
    expected_annulus_properties(d, t)
    return d, t


def check_tube_properties(
    actual: dict[str, float], diameter_m: float, thickness_m: float,
    *, tolerance: float = 0.15,
) -> dict[str, float]:
    """Reject non-circular or non-hollow catalog entries sharing two numbers.

    Robot catalogue names RO/RK/RPA are candidates only; we confirm their
    physical A/Iy/Iz/J against the annulus before accepting. Deviations can
    occur because of section manufacturing tolerances, so report deltas too.
    """
    expected = expected_annulus_properties(diameter_m, thickness_m)
    differences: dict[str, float] = {}
    for key, ideal in expected.items():
        value = float(actual[key])
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"Robot tube returned invalid {key}={value}")
        relative = value / ideal - 1.0
        differences[f"{key}_relative_difference_from_ideal"] = relative
        if abs(relative) > tolerance:
            raise ValueError(
                f"Robot section is not a verified CHS {diameter_m*1000:g}x"
                f"{thickness_m*1000:g}: {key} deviates {relative:+.1%} "
                "from a circular annulus. Refusing catalogue assignment."
            )
    return differences


def create_parametric_chs(
    labels: object, constants: object, name: str, material_name: str,
    diameter_m: float, thickness_m: float,
) -> dict[str, float]:
    """Build Robot's actual tube shape through CreateNonstd/CalcNonstdGeometry.

    Autodesk's API syntax: I_BST_NS_TUBE, I_BSST_USER_TUBE,
    I_BSNDV_TUBE_D and I_BSNDV_TUBE_T; dimensions are in metres.
    Unlike a numerical section with I_BSST_UNKNOWN, this has renderable
    geometry in Robot. Failure is fatal: do not hide it behind a line-only
    numerical fallback.
    """
    expected_annulus_properties(diameter_m, thickness_m)
    label = labels.Create(constants.I_LT_BAR_SECTION, name)
    data = label.Data
    data.Type = constants.I_BST_NS_TUBE
    data.ShapeType = constants.I_BSST_USER_TUBE
    shape = data.CreateNonstd(0)
    shape.SetValue(constants.I_BSNDV_TUBE_D, float(diameter_m))
    shape.SetValue(constants.I_BSNDV_TUBE_T, float(thickness_m))
    data.CalcNonstdGeometry()
    data.MaterialName = material_name
    labels.Store(label)
    saved = labels.Get(constants.I_LT_BAR_SECTION, name).Data
    properties = {
        key: float(saved.GetValue(getattr(constants, enum)))
        for key, enum in (
            ("A", "I_BSDV_AX"), ("Iy", "I_BSDV_IY"),
            ("Iz", "I_BSDV_IZ"), ("J", "I_BSDV_IX"),
        )
    }
    check_tube_properties(properties, diameter_m, thickness_m)
    return properties