using System.Linq;
using Qbiq.PathTool.Core;
using Xunit;

namespace Qbiq.PathTool.Tests
{
    public class MeshMathTests
    {
        [Fact]
        public void Feet_become_metres_with_the_axes_unchanged()
        {
            var v = MeshMath.ToMetresZUp(10, 20, 3);
            Assert.Equal(3.048, v[0], 9);
            Assert.Equal(6.096, v[1], 9);
            Assert.Equal(0.9144, v[2], 9);
        }

        [Fact]
        public void Opacity_comes_from_the_materials_transparency_percent()
        {
            Assert.Null(MeshMath.OpacityFromTransparency(0));
            Assert.Equal(0.6, MeshMath.OpacityFromTransparency(40));
            Assert.Equal(0.0, MeshMath.OpacityFromTransparency(100));
        }

        [Fact]
        public void Colours_become_lowercase_hex()
        {
            Assert.Equal("#ff8000", MeshMath.ToHex(255, 128, 0));
            Assert.Equal("#000000", MeshMath.ToHex(0, 0, 0));
        }
    }

    public class MeshBuilderTests
    {
        static readonly double[] A = { 0, 0, 0 }, B = { 1, 0, 0 }, C = { 0, 1, 0 };

        [Fact]
        public void Triangles_with_the_same_material_merge_into_one_mesh_with_offset_faces()
        {
            var b = new MeshBuilder();
            b.AddTriangle("wall", "#ffffff", null, A, B, C);
            b.AddTriangle("wall", "#ffffff", null, A, B, C);
            var meshes = b.Build();
            var m = Assert.Single(meshes);
            Assert.Equal(18, m.Verts.Count);                      // 6 vertices x 3
            Assert.Equal(new[] { 0, 1, 2, 3, 4, 5 }, m.Faces);
        }

        [Fact]
        public void Different_type_colour_or_opacity_stay_separate()
        {
            var b = new MeshBuilder();
            b.AddTriangle("wall", "#ffffff", null, A, B, C);
            b.AddTriangle("wall", "#000000", null, A, B, C);
            b.AddTriangle("floor", "#ffffff", null, A, B, C);
            b.AddTriangle("wall", "#ffffff", 0.5, A, B, C);
            Assert.Equal(4, b.Build().Count);
            Assert.Equal(12, b.VertexCount);
        }

        [Fact]
        public void An_empty_builder_builds_nothing()
        {
            Assert.Empty(new MeshBuilder().Build());
        }

        [Fact]
        public void Every_face_index_points_at_a_vertex()
        {
            var b = new MeshBuilder();
            for (var i = 0; i < 5; i++) b.AddTriangle(i % 2 == 0 ? "wall" : "floor", null, null, A, B, C);
            foreach (var m in b.Build())
                Assert.All(m.Faces, f => Assert.InRange(f, 0, m.Verts.Count / 3 - 1));
        }
    }
}
