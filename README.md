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