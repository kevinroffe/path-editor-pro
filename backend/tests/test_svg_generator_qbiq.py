import re

from revit_extractor import LevelGeometry
from svg_generator import generate_svg


def _geo(source: str) -> LevelGeometry:
    """A minimal floor: plate space, one 2-point wall, one 2-point door."""
    return LevelGeometry(
        level_name="L-0",
        elevation=0.0,
        walls=[[(0.0, 0.0), (100.0, 0.0)]],
        spaces=[[(0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (0.0, 50.0), (0.0, 0.0)]],
        doors=[[(40.0, 0.0), (60.0, 0.0)]],
        columns=[],
        windows=[],
        furniture=[],
        units_to_metres=0.01,
        source=source,
    )


def _layer_paths(svg: str, layer: str) -> list[tuple[str, str]]:
    """(d, style) for every path in one <g id=...> layer."""
    group = re.search(rf'<g id="{layer}">(.*?)</g>', svg, re.S).group(1)
    return re.findall(r'<path d="([^"]*)" style="([^"]*)"/>', group)


def _stroke(style: str) -> str:
    """The stroke colour declared in a style string."""
    return re.search(r"(?:^|;)stroke:([^;]+)", style).group(1)


def test_qbiq_walls_and_doors_are_stroked_open_paths():
    svg = generate_svg(_geo("qbiq"))
    for layer, colour in (("layer-walls", "#1e2d3d"), ("layer-doors", "#e07020")):
        paths = _layer_paths(svg, layer)
        assert len(paths) == 1
        d, style = paths[0]
        assert _stroke(style) == colour
        assert "fill:none" in style
        assert " Z" not in d


def test_qbiq_spaces_stay_filled():
    (_, style), = _layer_paths(generate_svg(_geo("qbiq")), "layer-spaces")
    assert style.startswith("fill:#dde6f0")


def test_ifc_and_demo_keep_the_fill_styles():
    for source in ("ifc", "demo"):
        svg = generate_svg(_geo(source))
        (wall_d, wall_style), = _layer_paths(svg, "layer-walls")
        (door_d, door_style), = _layer_paths(svg, "layer-doors")
        assert wall_style == "fill:#2c3e50;stroke:none"
        assert door_style == "fill:#e07020;stroke:none;opacity:0.85"
        assert wall_d.endswith(" Z") and door_d.endswith(" Z")
