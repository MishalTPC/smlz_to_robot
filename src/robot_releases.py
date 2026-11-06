"""End-release rules for angle and circular hollow-section Robot bars.

Mechanical convention (both member ends, LOCAL axes):
    UX, UY, UZ = fixed (translations continuous)
    RX = fixed (torsion about longitudinal bar X remains connected)
    RY, RZ = released (bending moment about either local axis = zero)

These are BAR-END releases, not node supports. A single Robot release label
is created once and assigned only to sections whose original Excel profile
is an angle (equal/unequal) or CHS. Steel catalogue names do not determine
the structural release rule.

Importing this module does not start Robot and works in offline unit tests.
"""
from __future__ import annotations

from typing import Any

from robot_profile_names import profile_key

BENDING_PIN_LABEL = "SMLX_ANGLE_CHS_BENDING_PIN"
FIXED_DOFS = ("UX", "UY", "UZ", "RX")
RELEASED_DOFS = ("RY", "RZ")


def needs_bending_pin(section: Any) -> bool:
    """Classify from source Excel geometry, never catalogue/fallback labels."""
    section_type = str(getattr(section, "section_type", "") or "").strip().upper()
    if section_type in {
        "ANGLE", "EQUAL ANGLE", "UNEQUAL ANGLE", "EA", "AE", "UA", "AU", "CHS",
    }:
        return True
    name = str(getattr(section, "section_name", "") or "")
    standard = str(getattr(section, "section_standard", "") or "")
    key = profile_key(
        name, section_type=section_type, section_standard=standard,
    )
    return key is not None and key[0] in {"AE", "AU", "CHS"}


def create_bending_pin_label(labels: Any, c: Any, *,
                             name: str = BENDING_PIN_LABEL) -> str:
    """Create and verify a shared RY/RZ-only release on BOTH bar ends.

    Robot I_BERV_NONE means no release/fixed at the bar end.
    Robot I_BERV_STD means fully released. Setting all six directions
    explicitly guards against default values differing between versions.
    """
    label = labels.Create(c.I_LT_BAR_RELEASE, name)
    data = label.Data
    for end in (data.StartNode, data.EndNode):
        for dof in FIXED_DOFS:
            setattr(end, dof, c.I_BERV_NONE)
        for dof in RELEASED_DOFS:
            setattr(end, dof, c.I_BERV_STD)
    labels.Store(label)

    stored = labels.Get(c.I_LT_BAR_RELEASE, name).Data
    for end_name in ("StartNode", "EndNode"):
        end = getattr(stored, end_name)
        for dof in FIXED_DOFS:
            if int(getattr(end, dof)) != int(c.I_BERV_NONE):
                raise RuntimeError(
                    f"Robot release {name}: {end_name}.{dof} is not fixed"
                )
        for dof in RELEASED_DOFS:
            if int(getattr(end, dof)) != int(c.I_BERV_STD):
                raise RuntimeError(
                    f"Robot release {name}: {end_name}.{dof} is not released"
                )
    return name


def assign_bending_pin(bar: Any, c: Any, label_name: str) -> None:
    """Assign the release without modifying the bar's section or material."""
    bar.SetLabel(c.I_LT_BAR_RELEASE, label_name)
    # RobotBar.HasLabel is exposed by the COM API. Test doubles may omit it.
    if hasattr(bar, "HasLabel") and not bool(bar.HasLabel(c.I_LT_BAR_RELEASE)):
        raise RuntimeError(
            f"Robot bar {getattr(bar, 'Number', '?')} did not accept "
            f"the end-release label {label_name!r}"
        )
