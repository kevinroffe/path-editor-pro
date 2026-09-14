"""
svg_generator.py
----------------
Converts a LevelGeometry object into an SVG string.

Y-axis fix
----------
DXF/IFC use a right-handed coordinate system where Y increases upward.
SVG Y increases downward.  We fix this by negating every Y coordinate
and adjusting the viewBox accordingly.  The SVG origin is NOT shifted
in X — raw model X coordinates are preserved so route coordinates map
1-to-1 with the model.  For Y, the relationship is: svg_y = -model_y.
The export layer accounts for this when writing Enscape XML.
"""

from __future__ import annotations
import html
from typing import List, Tuple
from revit_extractor import LevelGeometry, Polyline

MARGIN_FRACTION = 0.03


def generate_svg(geo: LevelGeometry) -> str:
    xmin0, ymin0, xmax0, ymax0 = geo.bounds()
    ext    = max(xmax0 - xmin0, ymax0 - ymin0, 1.0)
    margin = ext * MARGIN_FRACTION

    # After Y-flip: model_y → svg_y = -model_y
    # So model ymin becomes svg -ymin (large positive) → svg viewBox top = -ymax
    svg_xmin = xmin0 - margin
    svg_ymin = -ymax0 - margin   # top of viewBox after flip
    vw = (xmax0 - xmin0) + 2 * margin
    vh = (ymax0 - ymin0) + 2 * margin

    is_dxf = (geo.source == "dxf")

    sw = ext * 0.0008   # adaptive stroke width

    if is_dxf:
        # DXF entities are raw (often open) line/arc geometry, not closed
        # footprint polygons like IFC's mesh outlines — so every category is
        # stroked, not filled, same treatment as walls always had.
        STYLE_WALL      = f'fill:none;stroke:#1e2d3d;stroke-width:{sw:.4f};stroke-linecap:round;stroke-linejoin:round'
        STYLE_DOOR      = f'fill:none;stroke:#e07020;stroke-width:{sw:.4f};stroke-linecap:round;stroke-linejoin:round'
        STYLE_WINDOW    = f'fill:none;stroke:#6aabcc;stroke-width:{sw:.4f};stroke-linecap:round;stroke-linejoin:round'
        STYLE_COLUMN    = f'fill:none;stroke:#7f8c8d;stroke-width:{sw:.4f};stroke-linecap:round;stroke-linejoin:round'
        STYLE_FURNITURE = f'fill:none;stroke:#5a7a8a;stroke-width:{sw*0.7:.4f};stroke-linecap:round;stroke-linejoin:round;opacity:0.6'
    else:
        space_sw = ext * 0.0005
        furn_sw  = ext * 0.0006
        STYLE_WALL      = 'fill:#2c3e50;stroke:none'
        STYLE_SPACE     = f'fill:#dde6f0;stroke:#b0bfcf;stroke-width:{space_sw:.4f}'
        STYLE_DOOR      = 'fill:#e07020;stroke:none;opacity:0.85'
        STYLE_COLUMN    = 'fill:#7f8c8d;stroke:none'
        STYLE_WINDOW    = f'fill:#a8d4e8;stroke:#6aabcc;stroke-width:{space_sw:.4f};opacity:0.9'
        STYLE_FURNITURE = f'fill:none;stroke:#5a7a8a;stroke-width:{furn_sw:.4f};opacity:0.7'

    out: List[str] = []
    out.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" id="floorplan-svg" '
        f'viewBox="{svg_xmin:.3f} {svg_ymin:.3f} {vw:.3f} {vh:.3f}" '
        f'width="100%" height="100%">'
    )
    out.append(
        f'  <!-- source:{geo.source} level:{html.escape(geo.level_name)} '
        f'units_to_m:{geo.units_to_metres:.6f} extent:{ext:.2f} y_flipped:true -->'
    )
    # Background
    out.append(
        f'  <rect x="{svg_xmin:.3f}" y="{svg_ymin:.3f}" '
        f'width="{vw:.3f}" height="{vh:.3f}" fill="#f8fafc"/>'
    )

    if is_dxf:
        out.append('  <g id="layer-dxf-walls">')
        for poly in geo.walls:
            out.append(f'    {_path(poly, STYLE_WALL, close=False)}')
        out.append('  </g>')
        out.append('  <g id="layer-dxf-columns">')
        for poly in geo.columns:
            out.append(f'    {_path(poly, STYLE_COLUMN, close=False)}')
        out.append('  </g>')
        out.append('  <g id="layer-dxf-doors">')
        for poly in geo.doors:
            out.append(f'    {_path(poly, STYLE_DOOR, close=False)}')
        out.append('  </g>')
        out.append('  <g id="layer-dxf-windows">')
        for poly in geo.windows:
            out.append(f'    {_path(poly, STYLE_WINDOW, close=False)}')
        out.append('  </g>')
        out.append('  <g id="layer-dxf-furniture">')
        for poly in geo.furniture:
            out.append(f'    {_path(poly, STYLE_FURNITURE, close=False)}')
        out.append('  </g>')
    else:
        out.append('  <g id="layer-spaces">')
        for poly in geo.spaces:
            out.append(f'    {_path(poly, STYLE_SPACE, close=True)}')
        out.append('  </g>')
        out.append('  <g id="layer-walls">')
        for poly in geo.walls:
            out.append(f'    {_path(poly, STYLE_WALL, close=True)}')
        out.append('  </g>')
        out.append('  <g id="layer-doors">')
        for poly in geo.doors:
            out.append(f'    {_path(poly, STYLE_DOOR, close=True)}')
        out.append('  </g>')
        out.append('  <g id="layer-windows">')
        for poly in geo.windows:
            out.append(f'    {_path(poly, STYLE_WINDOW, close=True)}')
        out.append('  </g>')
        out.append('  <g id="layer-columns">')
        for poly in geo.columns:
            out.append(f'    {_path(poly, STYLE_COLUMN, close=True)}')
        out.append('  </g>')
        out.append('  <g id="layer-furniture">')
        for poly in geo.furniture:
            out.append(f'    {_path(poly, STYLE_FURNITURE, close=True)}')
        out.append('  </g>')

    out.append('</svg>')
    return '\n'.join(out)


def _path(poly: Polyline, style: str, close: bool) -> str:
    if len(poly) < 2:
        return ''
    # Negate Y to flip coordinate system
    d = f'M {poly[0][0]:.3f},{-poly[0][1]:.3f}'
    for x, y in poly[1:]:
        d += f' L {x:.3f},{-y:.3f}'
    if close:
        d += ' Z'
    return f'<path d="{d}" style="{style}"/>'
