"""Keeps the 3D view smooth on real Revit geometry.

reduce_meshes merges meshes that share a material (one draw call each) and, only when the model is over
its vertex budget, drops whole meshes by type (lights, other, furniture first), smallest first within a type. Walls and floors are never dropped, so the building
shell stays whole even when the budget cannot be met.
"""

PROTECTED_TYPES = frozenset({"wall", "floor"})
# Over budget, whole meshes go in this order (first = least missed); a type not listed goes first.
DROP_ORDER = ("light", "other", "furniture", "beam", "stair", "column", "window", "door", "ceiling")


def _count(mesh: dict) -> int:
    return len(mesh["verts"]) // 3


def _extent(mesh: dict) -> float:
    """Longest side of the mesh's bounding box."""
    v = mesh["verts"]
    return max(max(v[a::3]) - min(v[a::3]) for a in range(3)) if v else 0.0


def _merge(meshes: list) -> list:
    groups: dict = {}
    for m in meshes:
        g = groups.setdefault((m["type"], m.get("color"), m.get("opacity")),
                              {"type": m["type"], "verts": [], "faces": [],
                               "color": m.get("color"), "opacity": m.get("opacity")})
        offset = len(g["verts"]) // 3
        g["verts"].extend(m["verts"])
        g["faces"].extend(i + offset for i in m["faces"])
    return list(groups.values())


def reduce_meshes(meshes: list, max_vertices: int = 400_000) -> list:
    """Meshes merged by (type, colour, opacity); over budget, smallest non-wall/floor pieces are dropped first."""
    total = sum(_count(m) for m in meshes)
    if total <= max_vertices:
        return _merge(meshes)
    def drop_key(i):
        kind = meshes[i]["type"]
        return (DROP_ORDER.index(kind) if kind in DROP_ORDER else -1, _extent(meshes[i]))

    droppable = sorted((i for i, m in enumerate(meshes) if m["type"] not in PROTECTED_TYPES), key=drop_key)
    dropped = set()
    for i in droppable:
        if total <= max_vertices:
            break
        dropped.add(i)
        total -= _count(meshes[i])
    return _merge([m for i, m in enumerate(meshes) if i not in dropped])
