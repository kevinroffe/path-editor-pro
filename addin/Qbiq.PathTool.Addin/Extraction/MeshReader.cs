// Turns the geometry of Revit elements into the contract's meshes: triangulated faces, merged per material,
// in metres and Z-up with the model's own origin. Read-only. Linked instances are not entered.
using System.Collections.Generic;
using Autodesk.Revit.DB;
using Qbiq.PathTool.Core;

namespace Qbiq.PathTool.Addin.Extraction
{
    public sealed class MeshReader
    {
        readonly Document doc;
        readonly MeshBuilder builder = new MeshBuilder();
        readonly Options options = new Options { DetailLevel = ViewDetailLevel.Medium, ComputeReferences = false, IncludeNonVisibleObjects = false };
        readonly Dictionary<ElementId, MaterialLook> materials = new Dictionary<ElementId, MaterialLook>();

        sealed class MaterialLook { public string Color; public double? Opacity; }

        public MeshReader(Document doc) { this.doc = doc; }

        public int VertexCount => builder.VertexCount;

        public void AddElement(Element element, string type)
        {
            var geometry = element.get_Geometry(options);
            if (geometry != null) Walk(geometry, type);
        }

        public List<MeshPayload> Build() => builder.Build();

        void Walk(GeometryElement geometry, string type)
        {
            foreach (var obj in geometry)
            {
                if (obj.Visibility != Visibility.Visible) continue;
                if (obj is Solid solid) AddSolid(solid, type);
                else if (obj is GeometryInstance instance) Walk(instance.GetInstanceGeometry(), type);   // family geometry, already transformed
            }
        }

        void AddSolid(Solid solid, string type)
        {
            if (solid == null || solid.Faces.Size == 0) return;
            foreach (Face face in solid.Faces)
            {
                var look = LookOf(face.MaterialElementId);
                var mesh = face.Triangulate();
                for (var i = 0; i < mesh.NumTriangles; i++)
                {
                    var t = mesh.get_Triangle(i);
                    builder.AddTriangle(type, look.Color, look.Opacity, Metres(t.get_Vertex(0)), Metres(t.get_Vertex(1)), Metres(t.get_Vertex(2)));
                }
            }
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
