// Turns the geometry of Revit elements into the contract's meshes: triangulated faces, merged per material, in metres and
// Z-up with the model's own origin. The elements come from the active 3D view when there is one (so hidden categories, view
// filters and the section box apply as in Enscape), else from the whole model at Fine detail in the view's phase and the primary
// design option; inside the crop, for the whole building. Read-only. Linked models and CAD imports are not entered.
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Qbiq.PathTool.Core;

namespace Qbiq.PathTool.Addin.Extraction
{
    public sealed class MeshReader
    {
        /// <summary>Over this many vertices only the building shell (walls, floors, ceilings, roofs) is still read.</summary>
        public const int VertexBudget = 1500000;
        const double Far = 1e7;

        // Mesh types are the names the 3D view colours by.
        static readonly Dictionary<BuiltInCategory, string> Types = new Dictionary<BuiltInCategory, string>
        {
            { BuiltInCategory.OST_Walls, "wall" }, { BuiltInCategory.OST_Floors, "floor" }, { BuiltInCategory.OST_Ceilings, "ceiling" },
            { BuiltInCategory.OST_Roofs, "roof" }, { BuiltInCategory.OST_Doors, "door" }, { BuiltInCategory.OST_Windows, "window" },
            { BuiltInCategory.OST_CurtainWallPanels, "window" }, { BuiltInCategory.OST_CurtainWallMullions, "frame" },
            { BuiltInCategory.OST_Columns, "column" }, { BuiltInCategory.OST_StructuralColumns, "column" },
            { BuiltInCategory.OST_StructuralFraming, "beam" }, { BuiltInCategory.OST_Stairs, "stair" },
            { BuiltInCategory.OST_Furniture, "furniture" }, { BuiltInCategory.OST_FurnitureSystems, "furniture" },
            { BuiltInCategory.OST_Casework, "furniture" }, { BuiltInCategory.OST_LightingFixtures, "light" },
        };

        // Huge or non-building model categories: the crop is for dropping the surroundings, but these are never wanted.
        static readonly HashSet<BuiltInCategory> Skipped = new HashSet<BuiltInCategory>
        {
            BuiltInCategory.OST_Topography, BuiltInCategory.OST_Site, BuiltInCategory.OST_Planting, BuiltInCategory.OST_Entourage,
            BuiltInCategory.OST_Roads, BuiltInCategory.OST_Parking,
            BuiltInCategory.OST_RvtLinks,       // linked Revit models are out of version one: never pulled in whole through the view
            // Spatial and conceptual elements: no surfaces anyone walks past (a whole-model read would otherwise meet them).
            BuiltInCategory.OST_Rooms, BuiltInCategory.OST_Areas, BuiltInCategory.OST_MEPSpaces, BuiltInCategory.OST_Mass,
        };

        static readonly string[] ShellFirst = { "wall", "floor", "ceiling", "roof" };

        readonly Document doc;
        readonly View3D view;                 // null: the whole model
        readonly System.Func<Element, bool> inScope;
        readonly MeshBuilder builder = new MeshBuilder();
        readonly Options options;
        // An element that gives nothing through the view (a Coarse view hides much family geometry) is read again at Fine.
        readonly Options fine = new Options { DetailLevel = ViewDetailLevel.Fine, ComputeReferences = false, IncludeNonVisibleObjects = false };
        readonly Dictionary<ElementId, MaterialLook> materials = new Dictionary<ElementId, MaterialLook>();

        /// <summary>Per mesh type: elements read, read only at Fine, empty, failed.</summary>
        public MeshScan Scan { get; } = new MeshScan();

        sealed class MaterialLook { public string Color; public double? Opacity; }

        /// <param name="view">The 3D view to read through, or null for the whole model.</param>
        /// <param name="inScope">Phase and design-option check for a whole-model read (a view applies its own).</param>
        public MeshReader(Document doc, View3D view, System.Func<Element, bool> inScope)
        {
            this.doc = doc;
            this.view = view;
            this.inScope = inScope;
            options = view == null ? fine : new Options { View = view, ComputeReferences = false, IncludeNonVisibleObjects = false };
        }

        /// <summary>The whole building (as the view shows it, if any), inside the crop (or all of it). The shell is read first so the budget never costs it.</summary>
        public List<MeshPayload> Read(CropBox? crop)
        {
            var collector = (view == null ? new FilteredElementCollector(doc) : new FilteredElementCollector(doc, view.Id))
                .WhereElementIsNotElementType();
            if (crop.HasValue)
            {
                var c = crop.Value;
                collector = collector.WherePasses(new BoundingBoxIntersectsFilter(
                    new Outline(new XYZ(c.XMin, c.YMin, -Far), new XYZ(c.XMax, c.YMax, Far))));
            }
            var typed = new List<KeyValuePair<Element, string>>();
            foreach (var element in collector)
            {
                if (view == null && (element is ImportInstance || !inScope(element))) continue;
                var type = TypeOf(element);
                if (type != null) typed.Add(new KeyValuePair<Element, string>(element, type));
            }
            foreach (var pair in typed.OrderBy(p => System.Array.IndexOf(ShellFirst, p.Value) is var i && i >= 0 ? i : ShellFirst.Length))
                AddElement(pair.Key, pair.Value);
            return builder.Build();
        }

        static string TypeOf(Element element)
        {
            var category = element.Category;
            if (category == null || category.CategoryType != CategoryType.Model) return null;
            var id = category.BuiltInCategory;
            if (Skipped.Contains(id)) return null;
            return Types.TryGetValue(id, out var type) ? type : "other";
        }

        void AddElement(Element element, string type)
        {
            if (!MeshBudget.Allows(type, builder.VertexCount, VertexBudget)) return;
            try
            {
                var before = builder.VertexCount;
                var geometry = element.get_Geometry(options);
                if (geometry != null) Walk(geometry, type);
                if (builder.VertexCount > before) { Scan.Count(type, MeshOutcome.Read); return; }
                if (view == null) { Scan.Count(type, MeshOutcome.Empty); return; }     // already read at Fine
                var atFine = element.get_Geometry(fine);
                if (atFine != null) Walk(atFine, type);
                Scan.Count(type, builder.VertexCount > before ? MeshOutcome.ReadAtFine : MeshOutcome.Empty);
            }
            catch (System.Exception)
            {
                SkippedElements++;                       // one element Revit cannot give geometry for must not cost the whole model
                Scan.Count(type, MeshOutcome.Failed);
            }
        }

        /// <summary>Elements whose geometry could not be read (Revit failed to build it); the rest of the model is still read.</summary>
        public int SkippedElements;

        void Walk(GeometryElement geometry, string type)
        {
            foreach (var obj in geometry)
            {
                if (obj.Visibility != Visibility.Visible) continue;
                if (obj is Solid solid) AddSolid(solid, type);
                else if (obj is Mesh mesh) AddMesh(mesh, type);           // imported models (SketchUp, FBX, DWG) inside families
                else if (obj is GeometryInstance instance)
                {
                    var inner = instance.GetInstanceGeometry();                                          // family geometry, already transformed
                    if (inner != null) Walk(inner, type);
                }
            }
        }

        void AddSolid(Solid solid, string type)
        {
            if (solid == null || solid.Faces.Size == 0) return;
            foreach (Face face in solid.Faces)
            {
                var mesh = face.Triangulate();           // null when Revit cannot facet this face ("Problems during faceting")
                if (mesh != null) AddTriangles(mesh, face.MaterialElementId, type);
            }
        }

        void AddMesh(Mesh mesh, string type)
        {
            if (mesh != null && mesh.NumTriangles > 0) AddTriangles(mesh, mesh.MaterialElementId, type);
        }

        void AddTriangles(Mesh mesh, ElementId materialId, string type)
        {
            var look = LookOf(materialId);
            var vertices = new List<double[]>(mesh.Vertices.Count);
            foreach (var v in mesh.Vertices) vertices.Add(Metres(v));
            var indices = new List<int>(mesh.NumTriangles * 3);
            for (var i = 0; i < mesh.NumTriangles; i++)
            {
                var t = mesh.get_Triangle(i);
                indices.Add((int)t.get_Index(0));
                indices.Add((int)t.get_Index(1));
                indices.Add((int)t.get_Index(2));
            }
            builder.AddIndexed(type, look.Color, look.Opacity, vertices, indices);
        }

        static double[] Metres(XYZ p) => MeshMath.ToMetresZUp(p.X, p.Y, p.Z);

        MaterialLook LookOf(ElementId materialId)
        {
            if (materials.TryGetValue(materialId, out var cached)) return cached;
            var look = new MaterialLook();
            if (materialId != ElementId.InvalidElementId && doc.GetElement(materialId) is Material material)
            {
                var c = material.Color;
                if (c != null && c.IsValid) look.Color = MeshMath.ToHex(c.Red, c.Green, c.Blue);
                look.Opacity = MeshMath.OpacityFromTransparency(material.Transparency);
            }
            materials[materialId] = look;
            return look;
        }
    }
}
