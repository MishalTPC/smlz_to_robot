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
committed above `src/`) and CSV files are written to `output/`:

- `nodes.csv`: `node_id`, `x`, `y`, `z`.
- `elements.csv`: `element_id`, `node1`, `node2`, `property_id` plus the source
  member ID, beam/column role, local normal, SMLX offsets and reference axis.
- `properties.csv`: a distinct `property_id` for every section/material pair;
  name, type, dimensions, A, Iy, Iz, Iyz, J, Iw, shear areas and material data.

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