// Pure helpers for turning Revit geometry into the contract's meshes: metres, Z-up, same origin as the plan.
using System;
using System.Collections.Generic;

namespace Qbiq.PathTool.Core
{
    public static class MeshMath
    {
        public const double FeetToMetres = 0.3048;

        /// <summary>A Revit point in feet as metres; the axes stay as they are (Revit is Z-up, like the contract).</summary>
        public static double[] ToMetresZUp(double xFt, double yFt, double zFt) =>
            new[] { xFt * FeetToMetres, yFt * FeetToMetres, zFt * FeetToMetres };

        /// <summary>Revit material transparency (0 to 100 percent) as opacity; null means fully opaque.</summary>
        public static double? OpacityFromTransparency(int percent) =>
            percent <= 0 ? (double?)null : Math.Round(Math.Max(0.0, 1.0 - percent / 100.0), 3);

        public static string ToHex(byte r, byte g, byte b) => "#" + r.ToString("x2") + g.ToString("x2") + b.ToString("x2");
    }

    /// <summary>Which element types are still read once the model is over its vertex budget.</summary>
    public static class MeshBudget
    {
        /// <summary>
        /// Detail is kept only while under budget. The building shell (walls, floors, ceilings, roofs) is kept past it, so the
        /// building never loses its walls to furniture, but even the shell stops at three times the budget: a whole-building read
        /// of a huge project must still fit in one upload.
        /// </summary>
        public static bool Allows(string type, int currentVertices, int budget)
        {
            var shell = type == "wall" || type == "floor" || type == "ceiling" || type == "roof";
            return currentVertices < (shell ? budget * 3L : budget);
        }
    }

    /// <summary>The height band of a level, in feet: elements that reach into it belong to it, including walls that span several levels.</summary>
    public struct LevelBand
    {
        public const double DefaultStoreyFt = 15.0;
        const double Margin = 0.1;      // keeps the slab below and the wall tops of the storey beneath out of the band

        public double Low, High;

        public static LevelBand For(double elevation, IEnumerable<double> allElevations)
        {
            var above = new List<double>();
            foreach (var e in allElevations) if (e > elevation + 1e-9) above.Add(e);
            above.Sort();
            var top = above.Count > 0 ? above[0] : elevation + DefaultStoreyFt;
            return new LevelBand { Low = elevation + Margin, High = top - Margin };
        }
    }

    /// <summary>Collects triangles and merges them into one mesh per (type, colour, opacity).</summary>
    public sealed class MeshBuilder
    {
        sealed class Key : IEquatable<Key>
        {
            public string Type, Color; public double? Opacity;
            public bool Equals(Key o) => o != null && Type == o.Type && Color == o.Color && Opacity == o.Opacity;
            public override bool Equals(object o) => Equals(o as Key);
            public override int GetHashCode() => (Type ?? "").GetHashCode() * 31 + (Color ?? "").GetHashCode() * 7 + (Opacity ?? -1).GetHashCode();
        }

        readonly Dictionary<Key, MeshPayload> meshes = new Dictionary<Key, MeshPayload>();
        readonly List<Key> order = new List<Key>();

        public int VertexCount { get; private set; }

        public void AddTriangle(string type, string color, double? opacity, double[] a, double[] b, double[] c)
        {
            var key = new Key { Type = type, Color = color, Opacity = opacity };
            if (!meshes.TryGetValue(key, out var mesh))
            {
                mesh = new MeshPayload { Type = type, Color = color, Opacity = opacity };
                meshes[key] = mesh;
                order.Add(key);
            }
            var first = mesh.Verts.Count / 3;
            foreach (var v in new[] { a, b, c }) mesh.Verts.AddRange(v);
            mesh.Faces.AddRange(new[] { first, first + 1, first + 2 });
            VertexCount += 3;
        }

        /// <summary>A triangulated face that already shares its vertices: indices into <paramref name="vertices"/>, three per triangle.</summary>
        public void AddIndexed(string type, string color, double? opacity, IReadOnlyList<double[]> vertices, IReadOnlyList<int> indices)
        {
            var key = new Key { Type = type, Color = color, Opacity = opacity };
            if (!meshes.TryGetValue(key, out var mesh))
            {
                mesh = new MeshPayload { Type = type, Color = color, Opacity = opacity };
                meshes[key] = mesh;
                order.Add(key);
            }
            var first = mesh.Verts.Count / 3;
            foreach (var v in vertices) mesh.Verts.AddRange(v);
            foreach (var i in indices) mesh.Faces.Add(first + i);
            VertexCount += vertices.Count;
        }

        public List<MeshPayload> Build()
        {
            var result = new List<MeshPayload>();
            foreach (var key in order) result.Add(meshes[key]);
            return result;
        }
    }
}
