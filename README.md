# SMLX to Robot: Phase 1 – model reader

This first stage reads an Autodesk Advance Steel SMLX file (or extracted archive)
into three linked pandas DataFrames. **No Autodesk Robot model is created yet.**
All Python code lives in `src/`.

## Set up (Windows / Python)

From the repository root, in the same Python environment where you installed
`sectionproperties`:

```powershell
python -m pip install -r src/requirements.txt
```

## Run the committed example

```powershell
python src/smlx_reader.py
```

By default, the input is `SMLX Test File 03.11.2026/` (the extracted sample
committed above `src/`) and CSV files **plus one Excel workbook** are written to `output/`:

- `nodes.csv`: `node_id`, `x`, `y`, `z`.
- `elements.csv`: `element_id`, `node1`, `node2`, `property_id` plus the source
  member ID, beam/column role, local normal, SMLX offsets and reference axis.
- `properties.csv`: a distinct `property_id` for every section/material pair;
  name, type, dimensions, A, Iy, Iz, Iyz, J, Iw, shear areas and material data.
- `smlx_model.xlsx`: a formatted, filterable Excel workbook containing all imported
  information, organized into separate worksheets.

## Excel workbook

The default `output/smlx_model.xlsx` contains:

| Worksheet | Contents |
|---|---|
| `Overview` | Input file, counts, model caveats and sheet guide |
| `Nodes` | All node IDs and coordinates |
| `Topology` | `element_id`, `node1`, `node2`, `property_id` |
| `Elements` | All element fields including SMLX IDs, member roles, normals and offsets |
| `Sections` | Unique SMLX profiles with geometric dimensions, A, Iy, Iz, Iyz, J, Iw and shear areas |
| `Materials` | Unique material grades, E, G, nu, fy, fu and density |
| `Properties` | **Complete unmodified `df_properties`**, one record per section/material combination |
| `Field Units` | SI units and notes for every exported column |

All data sheets have filterable Excel tables, frozen headings and readable
column widths. Missing values such as uncalculated section properties or
missing G are exported as **blank numeric cells**, not as the text `nan`.
All lengths, stresses and section properties retain the original **SI units**.

By default, running the Python reader produces **both CSV files and the workbook**.
To choose the workbook filename or disable only the Excel export:

```powershell
python src/smlx_reader.py --excel-file "output/model_review.xlsx"
python src/smlx_reader.py --no-excel
```

Export a workbook directly from existing DataFrames:

```python
from excel_export import export_smlx_workbook  # when `src` is on sys.path
export_smlx_workbook(df_nodes, df_elements, df_properties,
                     "output/smlx_model.xlsx", source="my_model.smlx")
```

The `Sections` and `Materials` views are deduplicated using their original SMLX
IDs. The `Topology.property_id` key links to `Properties.property_id`; each
property record then identifies the SMLX section and material. The `Elements`
sheet retains the complete member metadata needed in a future Robot import.
The workbook is intended for model review and audit rather than as the
authoritative source for reimport.

The same DataFrames are available programmatically:

```python
from smlx_reader import read_smlx  # when `src` is on sys.path

df_nodes, df_elements, df_properties = read_smlx()
```

To read the **original ZIP** rather than the extracted folder:

```powershell
python src/smlx_reader.py "SMLX Test File 03.11.2026.zip"
```

For a fast check without meshing or `sectionproperties` calculations:

```powershell
python src/smlx_reader.py --skip-analysis
```

For an **explicitly approved** Poisson's ratio of 0.30:

```powershell
python src/smlx_reader.py --poisson 0.30
```

By default, `sectionproperties` performs both geometric and warping analyses
once for each unique section. Mesh max triangle area (in mm²) is calculated as
`mesh_factor * minimum_thickness_mm**2`; use `--mesh-factor 0.25` for a finer mesh.

## Units and important limitations

**Every numeric geometric/mechanical field in the DataFrames uses SI units:**

| DataFrame property | Units |
|---|---|
| `x`, `y`, `z`, `h`, `b`, `tw`, `tf`, `t`, centroids and offsets | m |
| `A`, `Ay`, `Az` | m² |
| `Iy`, `Iz`, `Iyz`, `J` | m⁴ |
| `Iw` (warping constant) | m⁶ |
| `E`, `G`, `fy`, `fu` | Pa |
| `density` | kg/m³ |
| `principal_axis_deg` | degrees |

SMLX `m_tabGeometryPoints_*` are cross-section points in local `(y,z)`
coordinates. For I- and angle sections, their exported polygon is meshed
as-is; root radii not represented by the export are **not** invented.
CHS outer and inner radii are read from its geometry points and the smooth
CHS is reconstructed using `sectionproperties`' circular hollow section
library. Curved polygon segments with nonzero SMLX bulges are explicitly
rejected rather than silently approximated.

**Axis convention:** sectionproperties `x` corresponds to SMLX local `y` and
sectionproperties `y` to SMLX local `z`. Thus the reported `Iy` equals
sectionproperties `Ixx`, and `Iz` equals `Iyy`, both centroidal. The
shear-centre values returned by `get_sc()` are offsets **from the centroid**.
SMLX member normals and source offsets are retained for a later member-axis
conversion to Robot. Member lines are currently created from the **SMLX CAD
start/end reference coordinates**, not from adjusted analytical centre lines.
Intersections inside members, eccentricities, releases and supports are not
resolved into a fully connected structural model at this stage.

The sample material S275JR exports `E = 210 GPa`, `fy = 275 MPa`,
`fu = 430 MPa`, `density = 7850 kg/m³` and **nu = 0.0**. The default reader
preserves this reported value but deliberately leaves **G = NaN** and emits
an explicit warning rather than guessing nu for Robot. Supply `--poisson 0.30`
*only if you have checked that this override is appropriate.*

## Check the import

```powershell
python -m unittest discover -s src -p "test_*.py" -v
```

The tests check the committed example's 212 beams/columns, 200 unique CAD
endpoints, 4 sections, geometry dimensions, material values and cross-reference
integrity. When `sectionproperties` is installed, they also run the section
property calculations and check the CHS area against the annulus formula.

## South African Robot section database matching

The one-click `src/run_robot.py` now searches Robot's **ZA (SAISC 2010)**
steel-section database, followed by **SADEF**, through the Robot COM API.
The Python unit `src/robot_section_catalog.py` enumerates actual profiles
available in your Robot installation and matches sections by **family and
complete nominal size**, allowing spaces, multiplication symbols, decimal
formatting and the equal-angle alias `L` → `EA`. It does **not** guess the
closest section or silently use the wrong profile size.

For the supplied SMLX model the intended matching examples are:

- `UB254X146X31` → `UB 254x146x31`
- `UC152X152X30` → `UC 152x152x30`
- `L60X60X6` → `EA 60x60x6` (equal angle)
- `CHS101.6X4.0` → `CHS 101.6x4`

These are **naming examples**: the actual availability is checked at runtime,
and a profile is only loaded if found uniquely in Robot's selected database.
The label is loaded through `LoadFromDBase2(profile, database)`, so its
Robot catalogue geometry and parameters are retained. The associated S275JR
material is applied separately.

The independent geometric/mechanical properties calculated with
`sectionproperties` are **never deleted or overwritten** in the source
`output/smlx_model.xlsx` workbook. A companion
`output/smlx_from_excel.sections.json` audit records the real database name,
matched section name, the Robot-versus-Python section property differences,
and any sections that had to retain numerical labels. If the RTD filename
is numbered, the audit filename is numbered accordingly.

For an unavailable or ambiguous **CHS**, the one-click runner now creates
a **genuine parametric circular hollow section**, using Robot's
`I_BST_NS_TUBE` / `I_BSST_USER_TUBE` API, with outside diameter and wall
thickness obtained directly from the Excel `h` and `t` fields.
This replaces the previous `ShapeType=UNKNOWN` numerical CHS label,
which can appear as a line. The resulting label ends in `_TUBE`, and the
section audit records `"assignment": "parametric_tube"`.

Database name matching also accepts Robot's `RO`, `RK`, and `RPA`
tube/solid families as **potential** CHS names. These are accepted only
after verifying the actual Robot catalogue area, bending inertias and
torsion constant against the exact annulus for the exported diameter and
wall thickness. Solid tubes and similarly named non-CHS profiles are
rejected. The source workbook and its independent `sectionproperties`
results are never modified by this process.

For other profiles without a matching catalogue section, the importer
still creates a clearly marked `_NUM` numerical label. If a CHS tube
cannot be created through Robot's parametric API, the importer stops
with an explicit error instead of silently creating a line-only profile.
Set `STRICT_CATALOGUE = True` in
`src/run_robot.py` to stop if *any* catalogue section cannot be assigned.
Set `USE_SA_CATALOGUE = False` to intentionally use the previous numerical
section workflow. When using the command-line importer, use
`--sections catalogue` (default) or `--sections numeric`; add
`--strict-catalogue` to prohibit numerical fallbacks.

NOTE: `src/run_robot.py` uses `USE_SA_CATALOGUE = True` by default.
This enables the catalogue-or-parametric CHS workflow. Explicit
`--sections numeric` (or `USE_SA_CATALOGUE = False`) retains the earlier
numerical-only mode and does not create parametric tubes.

**Engineering caveat:** catalogue sections can have different properties from
the SMLX polygons because of fillets, wall-thickness conventions and local
axis orientations. The audit flags differences exceeding 15%, but all
catalogue values and section orientations still require review before
structural analysis. Project member eccentricities and end releases are not
yet translated.

## One-click Robot model builder (VS Code F5)

For the sample model, **open `src/run_robot.py` and press F5**.
This small Python runner loads `output/smlx_model.xlsx` and calls the
separate `RobotBuilder` unit. No command-line arguments are required.

The example S275JR material has `nu=0` in the SMLX export, so this
runner **explicitly assumes `nu=0.30`** and computes the shear modulus
from E. Adjust the `ASSUMED_POISSON` setting in `src/run_robot.py` if
your approved material value differs. This does *not* alter the spreadsheet.

**Save any existing Robot project before pressing F5.** The runner creates
a new 3D frame project; it does not silently modify an existing model.
It uses `REVIEW_ONLY=True` because the imported workbook omits some
analysis-critical behaviour (orientations, offsets, Iyz coupling, releases
and supports). The resulting Robot model must not be treated as an
analysis-ready design model.

**Important:** The runner now retains a Robot COM connection after saving
and pauses the terminal for inspection. Robot will remain available while
the Python session is paused; press Enter in the terminal when finished.
Releasing the final COM reference may then close an instance that Python
started. The same inspection pause applies when using the advanced
`robot_from_excel.py` command-line program. If the process has no
interactive console, reopen the saved RTD file using Robot.

The output is `output/smlx_from_excel.rtd`. If that file exists,
the runner chooses `smlx_from_excel_002.rtd`, etc., instead of
overwriting previous results. The advanced command-line interface remains
available through `src/robot_from_excel.py`.

## Python units / module separation

The Robot stage is separated into independent Python modules, similar to
Pascal units:

- `src/excel_model.py`: read the Excel workbook into pandas DataFrames,
  cross-check Nodes/Topology/Elements/Sections/Materials/Properties, and
  perform engineering preflight checks. No Robot dependency.
- `src/robot_builder.py`: dedicated Robot-building unit. Owns all COM
  interaction, node/bar creation, material and section labels, validation
  readback and `.rtd` saving. Exposes `RobotBuilder` and the compatible
  `create_robot_model()` function.
- `src/robot_from_excel.py`: minimal command-line entry point that calls
  the two units. Existing CLI commands continue to work.

The building unit can also be imported into other Python code:

```python
from excel_model import read_excel_model
from robot_builder import RobotBuilder

model = read_excel_model("output/smlx_model.xlsx")
builder = RobotBuilder()
report = builder.build_model(
    model,
    create_new_project=True,
    allow_approximations=True,
    poisson_override=0.30,  # Apply only after engineering approval.
    output="output/smlx_from_excel.rtd",
)
print(report)
```

`RobotBuilder` accepts optional injected `robot` and `constants` objects
for offline unit testing. It connects to Robot lazily; importing the module
or using `--dry-run` does not start Robot. A new project is only permitted
when `create_new_project=True`. See review-only limitations below.

## Phase 2: Excel workbook to Autodesk Robot (Python / pywin32)

The Python import script lives in `src/robot_from_excel.py`. It reads the
previously generated `output/smlx_model.xlsx` and creates a **new** 3D-frame
Robot model (`.rtd`) using Robot's COM API; Robot is required **only for this
second step**, on Windows. No VBA, CSV re-import, or `pyrobotstructural` is
required.

Install dependencies in the *same Python environment* that will run Robot:

```powershell
python -m pip install -r src/requirements.txt
```

**Inspect the workbook before modifying Robot:**

```powershell
python src/robot_from_excel.py --dry-run --poisson 0.30
```

The sample SMLX source exports `nu=0` and an empty shear modulus. Therefore
`--poisson 0.30` is **an explicit user-authorized engineering assumption**,
not a silent replacement. Do not use that override without confirming the
material property. If your workbook already has a verified `nu` and `G`,
omit the `--poisson` option.

**Create a review-only Robot model from the workbook:**

```powershell
python src/robot_from_excel.py --new-project --allow-approximations --poisson 0.30
```

Default output is `output/smlx_from_excel.rtd`. The script requires
`--new-project` because a new Robot project can replace an unsaved project
currently open in Robot. Save any existing work before running. An existing
RTD output file is not overwritten unless `--overwrite` is supplied.

Supported workbook worksheets:

| Sheet | Usage |
|---|---|
| Nodes | All node IDs and X/Y/Z coordinates, metres |
| Topology | Element IDs, node1/node2, property_id |
| Elements | Cross-check topology; retain member normals, offsets and source identifiers |
| Sections | Verify sections from the Properties sheet |
| Materials | Create project steel labels: E, nu, G, fy, density |
| Properties | Create custom Robot bar-section labels and section/material assignments |

All numerical section properties use **SI units**. Robot's section-label values
are `I_BSDV_AX=A`, `I_BSDV_IY=Iy`, `I_BSDV_IZ=Iz`,
`I_BSDV_IX=J`, plus the effective shear areas (`Ay`, `Az`).
The Robot material `RO` field expects **unit weight N/m³**, so the importer
uses `density_kg_m3 * 9.80665`. Robot section labels include the associated
material name. The imported `fy` is assigned to Robot's `RE` field.
The exported `fu` is retained in Excel rather than falsely equating it to
Robot's `RT` design limit.

**Analysis-critical limitations — review-only model:**

- Imported bars follow SMLX CAD reference-line endpoints. Internal member
  intersections are not split into nodes automatically.
- Member normals and section axis rotations (Robot `Gamma`) are **not**
  reconstructed. Review local \(y,z\) axes for *all* noncircular sections.
- SMLX member offsets/eccentricities are retained in Excel but **not applied**.
- Unsymmetric-section `Iyz` coupling (notably L angles) is not passed to
  Robot's numerical section definition; warping constant `Iw`, shear-centre
  offsets and geometric section outlines are also not transferred.
- No supports, member end releases, load cases, or loads are defined from this
  workbook; do **not** run or rely upon structural analysis without completing
  and validating the analytical model.

For members with nonzero offsets or sections with nonzero `Iyz`, the importer
**refuses** to build by default. The explicit `--allow-approximations` option
acknowledges these omissions and permits a *review-only* model. It never
silently invents restraints, connectivity or local axes.

The importer validates Excel worksheet schema, unique IDs, referential
integrity and duplicate section/material fields. It also reads back core
material and section properties from Robot after setting them and confirms
the node/member counts. Unit tests use simulated COM objects; the actual
Robot integration **must be checked on your Windows installation**:

```powershell
python -m unittest discover -s src -p "test_*.py" -v
```
