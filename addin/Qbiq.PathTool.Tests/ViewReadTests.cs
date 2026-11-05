using System.IO;
using System.Linq;
using Qbiq.PathTool.Core;
using Xunit;

namespace Qbiq.PathTool.Tests
{
    public class ViewChoiceTests
    {
        static readonly string[] Views = { "{3D}", "Exterior", "Interior walkthrough" };

        [Fact] public void An_active_3D_view_is_used() => Assert.Equal(ViewSource.Active, ViewChoice.Choose(true, Views));
        [Fact] public void Without_an_active_3D_view_the_default_3D_view_is_used() => Assert.Equal(ViewSource.Default, ViewChoice.Choose(false, Views));
        [Fact] public void No_3D_view_at_all_gives_none() => Assert.Equal(ViewSource.None, ViewChoice.Choose(false, new string[0]));
        [Fact] public void Other_3D_views_without_a_default_give_none() => Assert.Equal(ViewSource.None, ViewChoice.Choose(false, new[] { "Exterior" }));
        [Fact] public void None_comes_with_an_instruction() => Assert.Contains("Open a 3D view", ViewChoice.NoViewMessage);
        [Fact] public void An_active_3D_view_wins_even_if_the_list_is_empty() => Assert.Equal(ViewSource.Active, ViewChoice.Choose(true, new string[0]));
    }

    public class OverviewAndCropReadTests
    {
        static RecordedModelReader Reader() => RecordedModelReader.FromJson(File.ReadAllText(PayloadTests.FixturePath()));

        [Fact]
        public void An_overview_has_no_meshes_a_default_frame_and_the_level_list()
        {
            var p = Reader().ReadOverview("Level 1");
            Assert.True(p.Overview);
            Assert.Empty(p.Meshes);
            Assert.NotEmpty(p.Walls);
            Assert.Equal(new[] { "Level 1" }, p.Levels);
            Assert.Equal("Level 1", p.CurrentLevel);
            Assert.NotNull(p.CropDefault);
            Assert.True(p.CropDefault.XMax > p.CropDefault.XMin);
        }

        [Fact]
        public void A_cropped_read_keeps_only_what_touches_the_area()
        {
            var all = Reader().ReadModel("Level 1", null, true);
            var left = Reader().ReadModel("Level 1", CropBox.Normalise(0, 0, 25, 40), true);
            Assert.True(left.Walls.Count < all.Walls.Count);
            Assert.All(left.Walls, w => Assert.True(w.Min(pt => pt[0]) <= 25));
            Assert.DoesNotContain(left.Rooms, r => r.Polygon != null && r.Polygon.Min(pt => pt[0]) > 25);
            Assert.Equal(all.Meshes.Count, left.Meshes.Count);                    // 3D comes with the read
        }

        [Fact]
        public void A_read_without_meshes_says_to_keep_the_last_3D()
        {
            var p = Reader().ReadModel("Level 1", null, false);
            Assert.Empty(p.Meshes);
            Assert.True(p.KeepMeshes);
            Assert.False(p.Overview);
        }

        [Fact]
        public void A_crop_over_nothing_gives_an_empty_level_not_an_error()
        {
            var p = Reader().ReadModel("Level 1", CropBox.Normalise(500, 500, 600, 600), true);
            Assert.Empty(p.Walls);
            Assert.Empty(p.Rooms);
        }
    }

    public class PayloadExtrasTests
    {
        [Fact]
        public void The_new_optional_fields_round_trip_and_stay_out_of_the_json_when_unused()
        {
            var plain = PayloadJson.Serialize(new LevelPayload());
            Assert.DoesNotContain("levels", plain);
            Assert.DoesNotContain("keep_meshes", plain);
            Assert.DoesNotContain("overview", plain);
            Assert.DoesNotContain("crop_default", plain);

            var p = new LevelPayload
            {
                Levels = new System.Collections.Generic.List<string> { "L1", "L2" }, CurrentLevel = "L2", ViewName = "{3D}",
                KeepMeshes = true, Overview = true, CropDefault = CropRect.From(CropBox.Normalise(1, 2, 3, 4)),
            };
            var back = PayloadJson.Deserialize(PayloadJson.Serialize(p));
            Assert.Equal(new[] { "L1", "L2" }, back.Levels);
            Assert.Equal("L2", back.CurrentLevel);
            Assert.Equal("{3D}", back.ViewName);
            Assert.True(back.KeepMeshes && back.Overview);
            Assert.Equal(4.0, back.CropDefault.YMax);
        }

        [Fact]
        public void A_read_request_can_ask_to_keep_the_3D()
        {
            Assert.True(ReadRequest.Parse("{\"type\":\"readModel\",\"level\":\"L\",\"keep_meshes\":true}").KeepMeshes);
            Assert.False(ReadRequest.Parse("{\"type\":\"readModel\",\"level\":\"L\"}").KeepMeshes);
        }

        [Fact]
        public void Roofs_are_part_of_the_always_kept_shell()
        {
            Assert.True(MeshBudget.Allows("roof", 2_900_000, 1_000_000));
        }
    }
}

namespace Qbiq.PathTool.Tests
{
    public class MeshesRequestTests
    {
        [Fact] public void A_read_asks_for_the_3D_only_when_it_says_so()
        {
            Assert.True(Qbiq.PathTool.Core.ReadRequest.Parse("{\"type\":\"readModel\",\"level\":\"L\",\"meshes\":true}").Meshes);
            Assert.False(Qbiq.PathTool.Core.ReadRequest.Parse("{\"type\":\"readModel\",\"level\":\"L\"}").Meshes);
            Assert.False(Qbiq.PathTool.Core.ReadRequest.Parse("{\"type\":\"overview\"}").Meshes);
        }
    }
}
