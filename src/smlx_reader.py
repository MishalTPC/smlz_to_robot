"""Read Advance Steel SMLX files into linked structural-analysis DataFrames.

All spatial quantities in the resulting DataFrames use SI units:
coordinates/dimensions [m], areas [m^2], inertias/J [m^4], warping
constant [m^6], E/G/fy/fu [Pa] and density [kg/m^3].

This is an importer, not a Robot model creator. SMLX CAD reference lines are
retained unchanged; offsets, end releases and analytical connectivity must be
reviewed before creating the analysis model.
"""

from __future__ import annotations

import argparse
import logging
import math
import re
import warnings
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from excel_export import export_smlx_workbook

LOG = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SAMPLE = REPO_ROOT / "SMLX Test File 03.11.2026"
SECTION_KEYS = (
    "A", "Iy", "Iz", "Iyz", "J", "Iw", "Ay", "Az",
    "centroid_y", "centroid_z", "shear_centre_y", "shear_centre_z",
    "principal_axis_deg",
)


@dataclass(frozen=True)
class SectionDefinition:
    source_id: int
    name: str
    standard: str
    section_class: str
    points: tuple[tuple[float, float], ...]  # SMLX local y, z in metres
    bulges: tuple[float, ...]


@dataclass(frozen=True)
class MaterialDefinition:
    source_id: int
    name: str
    E: float
    nu: float
    fy: float
    fu: float
    density: float


def _value(parent: ET.Element, key: str, *, default: str | None = None) -> str:
    """Retrieve a CGREX value from a typed XML attribute."""
    node = parent.find(key)
    if node is None:
        if default is not None:
            return default
        raise ValueError(f"SMLX field {key!r} missing from {parent.tag!r}")
    for field in ("long", "double", "string"):
        if field in node.attrib:
            return node.attrib[field]
    raise ValueError(f"SMLX field {key!r} has no recognised value attribute")


def _reference(parent: ET.Element, key: str) -> int:
    return int(_value(parent, f"{key}/Members/m_nID"))


def _point(parent: ET.Element, key: str) -> tuple[float, float, float]:
    point = parent.find(f"{key}/Members")
    if point is None:
        raise ValueError(f"Missing 3D point: {key}")
    return tuple(float(_value(point, key)) for key in ("m_dfX", "m_dfY", "m_dfZ"))


def _load_xml(source: str | Path) -> ET.Element:
    """Accept the original SMLX/ZIP, an extracted directory, or its XML file."""
    source = Path(source).expanduser().resolve()
    if source.is_file() and source.suffix.lower() in (".zip", ".smlx", ".smlz"):
        with zipfile.ZipFile(source) as archive:
            names = [name for name in archive.namelist()
                     if re.search(r"(?:^|/)Contents/[^/]+\.xml$", name, re.I)]
            if len(names) != 1:
                raise ValueError(f"Expected one main SMLX XML file inside {source}, found {names}")
            data = archive.read(names[0])
    elif source.is_file() and source.suffix.lower() == ".xml":
        data = source.read_bytes()
    elif source.is_dir():
        names = sorted(source.glob("Contents/*.xml"))
        if not names:
            names = sorted(source.glob("**/Contents/*.xml"))
        if len(names) != 1:
            raise ValueError(f"Expected one main XML under a Contents folder in {source}, found {names}")
        data = names[0].read_bytes()
    else:
        raise FileNotFoundError(f"SMLX source does not exist or has an unsupported format: {source}")
    root = ET.fromstring(data)
    if root.tag != "Document":
        raise ValueError(f"Expected SMLX <Document>, found <{root.tag}>")
    return root


def _read_sections(root: ET.Element) -> dict[int, SectionDefinition]:
    sections: dict[int, SectionDefinition] = {}
    for obj in root.findall("./Object[@class='CGREXSection']"):
        meta = obj.find("./Object[@class='CGREXObject']/Members")
        details = obj.find("./Members")
        if meta is None or details is None:
            raise ValueError("Malformed CGREXSection object")
        source_id = int(_value(meta, "m_nID"))
        shape_points = []
        for item in details:
            if re.fullmatch(r"m_tabGeometryPoints_\d+", item.tag):
                coords = item.find("Members")
                if coords is None:
                    raise ValueError(f"Section {source_id} missing polygon-point coordinates")
                shape_points.append((int(item.tag.rsplit("_", 1)[1]),
                                     float(_value(coords, "m_dfY")),
                                     float(_value(coords, "m_dfZ"))))
        shape_points.sort(key=lambda row: row[0])
        bulges = []
        for item in details:
            if re.fullmatch(r"m_tabBulges_\d+", item.tag):
                bulges.append((int(item.tag.rsplit("_", 1)[1]), float(_value(details, item.tag))))
        bulges.sort()
        if not shape_points:
            raise ValueError(f"Section {source_id} has no cross-section polygon")
        if source_id in sections:
            raise ValueError(f"Duplicate SMLX section ID {source_id}")
        sections[source_id] = SectionDefinition(
            source_id=source_id,
            name=_value(details, "m_strName"),
            standard=_value(details, "m_strStandard", default=""),
            section_class=_value(details, "m_strClass", default=""),
            points=tuple((y, z) for _, y, z in shape_points),
            bulges=tuple(v for _, v in bulges),
        )
    if not sections:
        raise ValueError("No CGREXSection definitions found")
    return sections


def _read_materials(root: ET.Element) -> dict[int, MaterialDefinition]:
    materials: dict[int, MaterialDefinition] = {}
    for obj in root.findall("./Object[@class='CGREXMaterial']"):
        meta = obj.find("./Object[@class='CGREXObject']/Members")
        details = obj.find("./Members")
        if meta is None or details is None:
            raise ValueError("Malformed CGREXMaterial object")
        source_id = int(_value(meta, "m_nID"))
        if source_id in materials:
            raise ValueError(f"Duplicate SMLX material ID {source_id}")
        materials[source_id] = MaterialDefinition(
            source_id=source_id,
            name=_value(details, "m_strName"),
            E=float(_value(details, "m_dfYoung")),
            nu=float(_value(details, "m_dfPoisson")),
            fy=float(_value(details, "m_dfFy")),
            fu=float(_value(details, "m_dfFu")),
            density=float(_value(details, "m_dfDensity")),
        )
    if not materials:
        raise ValueError("No CGREXMaterial definitions found")
    return materials


def _distinct(values: list[float], tolerance: float = 1e-8) -> list[float]:
    """Sorted unique section coordinates (metres), suppressing roundoff."""
    result: list[float] = []
    for value in sorted(values):
        if not result or value - result[-1] > tolerance:
            result.append(value)
    return result


def _section_dimensions(section: SectionDefinition) -> dict[str, float | str]:
    """Dimensions obtained from the real section coordinates (all in metres)."""
    ys = _distinct([p[0] for p in section.points])
    zs = _distinct([p[1] for p in section.points])
    b, h = ys[-1] - ys[0], zs[-1] - zs[0]
    name = section.name.upper()
    dimensions: dict[str, float | str] = {
        "section_type": "UNKNOWN", "h": h, "b": b,
        "tw": math.nan, "tf": math.nan, "t": math.nan,
    }
    if name.startswith(("UB", "UC")) or section.section_class.upper() == "I":
        dimensions["section_type"] = "I"
        if len(ys) == 4 and len(zs) == 4:
            dimensions["tw"] = ys[2] - ys[1]
            dimensions["tf"] = (zs[1] - zs[0] + zs[3] - zs[2]) / 2
    elif name.startswith("L") and len(ys) >= 3 and len(zs) >= 3:
        dimensions["section_type"] = "ANGLE"
        # For the sample equal-angle shape the internal transition points
        # provide one leg thickness on each axis.
        if len(ys) == 3 and len(zs) == 3:
            t = min(ys[1] - ys[0], ys[2] - ys[1],
                    zs[1] - zs[0], zs[2] - zs[1])
            dimensions.update(t=t, tw=t, tf=t)
    elif name.startswith("CHS") or section.section_class.upper() == "O":
        dimensions["section_type"] = "CHS"
        # The SMLX profile has separate circular coordinates for the inner
        # and outer surfaces; these radii, not the name, set the thickness.
        radii = _distinct([math.hypot(y, z) for y, z in section.points], 1e-7)
        if len(radii) == 2:
            dimensions["t"] = radii[-1] - radii[0]
            dimensions["h"] = dimensions["b"] = 2 * radii[-1]
        else:
            raise ValueError(f"CHS {section.name}: cannot infer inner and outer radii from SMLX points")
    return dimensions


def _properties_from_geometry(
    section: SectionDefinition, dimensions: dict[str, float | str], mesh_factor: float,
) -> dict[str, float]:
    """Run sectionproperties in mm; convert all outputs back to SI."""
    try:
        from sectionproperties.analysis import Section
        from sectionproperties.pre.geometry import Geometry
        from sectionproperties.pre.library import circular_hollow_section
        from shapely.geometry import Polygon
    except ImportError as exc:
        raise RuntimeError(
            "Section analysis requires sectionproperties. Install into the current "
            "Python environment: python -m pip install sectionproperties"
        ) from exc

    if any(abs(v) > 1e-12 for v in section.bulges):
        raise NotImplementedError(
            f"Section {section.name} contains curved SMLX polygon segments (bulges). "
            "Exact arc reconstruction is not implemented; calculation stopped."
        )
    kind = dimensions["section_type"]
    thickness = float(dimensions["t"] if kind == "CHS" else
                      dimensions["tw"] if kind == "I" else
                      dimensions["t"])
    if not math.isfinite(thickness) or thickness <= 0:
        raise ValueError(f"Cannot determine a positive thickness for {section.name}")
    if kind == "CHS":
        geometry = circular_hollow_section(
            d=float(dimensions["h"]) * 1000,
            t=thickness * 1000,
            n=96,
        )
    else:
        coords_mm = [(y * 1000, z * 1000) for y, z in section.points]
        if coords_mm[0] == coords_mm[-1]:
            coords_mm.pop()
        polygon = Polygon(coords_mm)
        if not polygon.is_valid or polygon.area <= 0:
            raise ValueError(f"Invalid polygon extracted for section {section.name}")
        geometry = Geometry(polygon)

    mesh_area_mm2 = mesh_factor * (thickness * 1000) ** 2
    geometry.create_mesh(mesh_sizes=[mesh_area_mm2])
    analysis = Section(geometry=geometry)
    analysis.calculate_geometric_properties()
    analysis.calculate_warping_properties()
    # sectionproperties x coordinate = SMLX local y; its y = SMLX local z.
    # Thus Ixx (about x) is SMLX Iy, and Iyy is SMLX Iz.
    ixx, iyy, ixy = analysis.get_ic()
    ax, az = analysis.get_as()
    cy, cz = analysis.get_c()
    sc_y, sc_z = analysis.get_sc()  # relative to centroidal axes
    return {
        "A": analysis.get_area() * 1e-6,
        "Iy": ixx * 1e-12,
        "Iz": iyy * 1e-12,
        "Iyz": ixy * 1e-12,
        "J": analysis.get_j() * 1e-12,
        "Iw": analysis.get_gamma() * 1e-18,
        "Ay": ax * 1e-6,
        "Az": az * 1e-6,
        "centroid_y": cy * 1e-3,
        "centroid_z": cz * 1e-3,
        "shear_centre_y": sc_y * 1e-3,
        "shear_centre_z": sc_z * 1e-3,
        "principal_axis_deg": analysis.get_phi(),
    }


class _Nodes:
    def __init__(self, tolerance: float) -> None:
        if tolerance <= 0:
            raise ValueError("node_tolerance must be positive")
        self.tolerance = tolerance
        self.cells: dict[tuple[int, int, int], list[int]] = defaultdict(list)
        self.points: list[tuple[float, float, float]] = []

    def add(self, point: tuple[float, float, float]) -> int:
        if any(not math.isfinite(x) for x in point):
            raise ValueError(f"Nonfinite node coordinates {point}")
        key = tuple(math.floor(x / self.tolerance) for x in point)
        for ix in range(key[0] - 1, key[0] + 2):
            for iy in range(key[1] - 1, key[1] + 2):
                for iz in range(key[2] - 1, key[2] + 2):
                    for index in self.cells.get((ix, iy, iz), ()):
                        other = self.points[index - 1]
                        if math.dist(point, other) <= self.tolerance:
                            return index
        index = len(self.points) + 1
        self.points.append(point)
        self.cells[key].append(index)
        return index


def read_smlx(
    source: str | Path = DEFAULT_SAMPLE,
    *,
    calculate_properties: bool = True,
    mesh_factor: float = 0.5,
    node_tolerance: float = 1e-6,
    poisson_override: float | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (df_nodes, df_elements, df_properties) for an SMLX model.

    `poisson_override` replaces exported nu for all materials if supplied.
    Zero exported nu is left intact, with G unavailable (NaN), until the user
    explicitly specifies a value. The geometric section analysis needs no nu.
    """
    if mesh_factor <= 0:
        raise ValueError("mesh_factor must be positive")
    if poisson_override is not None and not (-1 < poisson_override < 0.5):
        raise ValueError("poisson_override must be between -1 and 0.5")

    root = _load_xml(source)
    sections = _read_sections(root)
    materials = _read_materials(root)
    node_store = _Nodes(node_tolerance)
    raw_members = []
    property_pairs: set[tuple[int, int]] = set()

    for obj in root.findall("./Object"):
        kind = obj.get("class")
        if kind not in ("CGREXBeam", "CGREXColumn"):
            continue
        member_data = obj.find("./Object[@class='CGREXLine']/Object[@class='CGREXMember']/Members")
        meta = obj.find("./Object[@class='CGREXLine']/Object[@class='CGREXMember']/Object[@class='CGREXObject']/Members")
        line = obj.find("./Object[@class='CGREXLine']/Members")
        if member_data is None or meta is None or line is None:
            raise ValueError(f"Malformed {kind} record")
        source_id = int(_value(meta, "m_nID"))
        start_section = _reference(line, "m_pSectionStart")
        end_section = _reference(line, "m_pSectionEnd")
        material_id = _reference(member_data, "m_pMaterial")
        if start_section != end_section:
            raise NotImplementedError(f"Tapered member {source_id}: sections {start_section} and {end_section} differ")
        if start_section not in sections:
            raise ValueError(f"Member {source_id} references unknown section {start_section}")
        if material_id not in materials:
            raise ValueError(f"Member {source_id} references unknown material {material_id}")
        start, end = _point(line, "m_pCADStart"), _point(line, "m_pCADEnd")
        node1, node2 = node_store.add(start), node_store.add(end)
        if node1 == node2:
            raise ValueError(f"Zero-length member {source_id}, at or below tolerance {node_tolerance} m")
        normal = _point(line, "m_pNormal")
        pair = (start_section, material_id)
        property_pairs.add(pair)
        raw_members.append({
            "element_id": len(raw_members) + 1,
            "node1": node1,
            "node2": node2,
            "_pair": pair,
            "smlx_member_id": source_id,
            "member_type": kind.removeprefix("CGREX"),
            "member_role": _value(member_data, "m_strRole", default=""),
            "normal_x": normal[0], "normal_y": normal[1], "normal_z": normal[2],
            "offset_start_x": float(_value(line, "m_vecOffsetStartX")),
            "offset_start_y": float(_value(line, "m_vecOffsetStartY")),
            "offset_end_x": float(_value(line, "m_vecOffsetEndX")),
            "offset_end_y": float(_value(line, "m_vecOffsetEndY")),
            "reference_axis": int(_value(line, "m_referenceAxis", default="0")),
        })
    if not raw_members:
        raise ValueError("No CGREXBeam or CGREXColumn members found")

    pairs = sorted(property_pairs)
    pair_ids = {pair: i for i, pair in enumerate(pairs, start=1)}
    rows = []
    cache = {}
    for section_id, material_id in pairs:
        section, material = sections[section_id], materials[material_id]
        dims = _section_dimensions(section)
        if section_id not in cache:
            cache[section_id] = (_properties_from_geometry(section, dims, mesh_factor)
                                 if calculate_properties else {key: math.nan for key in SECTION_KEYS})
        nu = poisson_override if poisson_override is not None else material.nu
        if not math.isfinite(nu) or nu == 0:
            warnings.warn(
                f"Material {material.name!r} has Poisson ratio {material.nu:g} in SMLX. "
                "Retaining the value but leaving G empty; set --poisson 0.30 "
                "after checking the correct material properties.",
                stacklevel=2,
            )
            G = math.nan
        else:
            G = material.E / (2 * (1 + nu))
        rows.append({
            "property_id": pair_ids[(section_id, material_id)],
            "section_name": section.name,
            "section_type": dims["section_type"],
            "section_standard": section.standard,
            "material_name": material.name,
            "smlx_section_id": section_id,
            "smlx_material_id": material_id,
            **{key: dims[key] for key in ("h", "b", "tw", "tf", "t")},
            **cache[section_id],
            "E": material.E, "G": G, "nu": nu,
            "fy": material.fy, "fu": material.fu,
            "density": material.density,
            "property_source": ("SMLX geometry + sectionproperties" if calculate_properties else "SMLX only; section analysis skipped"),
        })

    elements = []
    for record in raw_members:
        pair = record.pop("_pair")
        elements.append({
            "element_id": record["element_id"],
            "node1": record["node1"],
            "node2": record["node2"],
            "property_id": pair_ids[pair],
            **{key: value for key, value in record.items() if key != "element_id"},
        })
    df_nodes = pd.DataFrame(
        [{"node_id": i, "x": x, "y": y, "z": z}
         for i, (x, y, z) in enumerate(node_store.points, start=1)],
        columns=["node_id", "x", "y", "z"],
    )
    df_elements = pd.DataFrame(elements)
    df_properties = pd.DataFrame(rows)
    # Referential integrity: every member must point to two valid nodes and a property.
    node_ids, property_ids = set(df_nodes.node_id), set(df_properties.property_id)
    if (not set(df_elements.node1).issubset(node_ids)
            or not set(df_elements.node2).issubset(node_ids)
            or not set(df_elements.property_id).issubset(property_ids)):
        raise ValueError("Internal error: invalid node/property ID in element topology")
    LOG.info("Read %s nodes, %s members, %s section/material properties",
             len(df_nodes), len(df_elements), len(df_properties))
    return df_nodes, df_elements, df_properties


def main() -> None:
    parser = argparse.ArgumentParser(description="SMLX geometry -> 3 linked pandas DataFrames")
    parser.add_argument("source", nargs="?", type=Path, default=DEFAULT_SAMPLE,
                        help="Extracted SMLX directory, .smlx/.zip or source XML")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "output",
                        help="Folder for generated CSV files (default: output/)")
    parser.add_argument("--excel-file", type=Path, default=None,
                        help="Excel workbook destination (default: <output>/smlx_model.xlsx)")
    parser.add_argument("--no-excel", action="store_true",
                        help="Disable Excel workbook export; CSV files are still written")
    parser.add_argument("--mesh-factor", type=float, default=0.5,
                        help="Max triangle area / thickness^2 (default: 0.5)")
    parser.add_argument("--node-tolerance", type=float, default=1e-6,
                        help="Endpoint merge tolerance in m (default: 1e-6)")
    parser.add_argument("--poisson", type=float, default=None,
                        help="Explicit Poisson ratio override (e.g. 0.3; never assumed silently)")
    parser.add_argument("--skip-analysis", action="store_true",
                        help="Only parse topology and profile dimensions; skip sectionproperties")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    df_nodes, df_elements, df_properties = read_smlx(
        args.source,
        calculate_properties=not args.skip_analysis,
        mesh_factor=args.mesh_factor,
        node_tolerance=args.node_tolerance,
        poisson_override=args.poisson,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    for name, frame in (("nodes", df_nodes), ("elements", df_elements), ("properties", df_properties)):
        dest = args.output / f"{name}.csv"
        frame.to_csv(dest, index=False)
        print(f"Saved {len(frame):4d} rows to {dest}")
    if not args.no_excel:
        workbook_path = args.excel_file if args.excel_file is not None else args.output / "smlx_model.xlsx"
        dest = export_smlx_workbook(
            df_nodes, df_elements, df_properties, workbook_path, source=args.source,
        )
        print(f"Saved Excel workbook to {dest}")
    print("\nNodes:\n", df_nodes.head().to_string(index=False))
    print("\nElements:\n", df_elements.iloc[:, :4].head().to_string(index=False))
    print("\nSections and geometric properties (SI):\n",
          df_properties[["property_id", "section_name", "material_name", "A", "Iy", "Iz", "J"]].to_string(index=False))


if __name__ == "__main__":
    main()