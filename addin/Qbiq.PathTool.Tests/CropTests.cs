using System;
using System.Collections.Generic;
using System.Linq;
using Qbiq.PathTool.Core;
using Xunit;

namespace Qbiq.PathTool.Tests
{
    public class CropBoxTests
    {
        [Fact]
        public void Corners_in_any_order_normalise()
        {
            var a = CropBox.Normalise(10, 20, 0, 5);
            var b = CropBox.Normalise(0, 5, 10, 20);
            Assert.Equal((0.0, 5.0, 10.0, 20.0), (a.XMin, a.YMin, a.XMax, a.YMax));
            Assert.Equal((a.XMin, a.YMin, a.XMax, a.YMax), (b.XMin, b.YMin, b.XMax, b.YMax));
        }

        [Fact]
        public void Intersects_is_true_for_overlap_touch_and_containment_and_false_apart()
        {
            var box = CropBox.Normalise(0, 0, 10, 10);
            Assert.True(box.Intersects(5, 5, 15, 15));      // overlap
            Assert.True(box.Intersects(10, 0, 20, 10));     // touching edge
            Assert.True(box.Intersects(2, 2, 3, 3));        // inside
            Assert.True(box.Intersects(-5, -5, 20, 20));    // contains the box
            Assert.False(box.Intersects(11, 0, 20, 10));    // apart in x
            Assert.False(box.Intersects(0, 11, 10, 20));    // apart in y
        }

        [Fact]
        public void A_tiny_box_is_not_usable()
        {
            Assert.False(CropBox.Normalise(0, 0, 0.5, 0.5).IsUsable);
            Assert.False(CropBox.Normalise(0, 0, 50, 0).IsUsable);     // no height at all
            Assert.True(CropBox.Normalise(0, 0, 10, 10).IsUsable);
        }
    }

    public class CropDefaultTests
    {
        static IEnumerable<IEnumerable<double[]>> Line(IEnumerable<double[]> points) => new[] { points };

        [Fact]
        public void Default_ignores_a_far_outlier()
        {
            var points = Enumerable.Range(0, 100).Select(i => new[] { (double)i, (double)i }).ToList();
            points.Add(new[] { 10000.0, 10000.0 });                    // a distant site outline vertex
            var box = Crop.Default(Line(points));
            Assert.True(box.IsUsable);
            Assert.InRange(box.XMax, 90, 110);
            Assert.InRange(box.YMax, 90, 110);
            Assert.InRange(box.XMin, -10, 5);
        }

        [Fact]
        public void Default_grows_the_box_a_little()
        {
            var points = Enumerable.Range(0, 101).Select(i => new[] { (double)i, (double)i }).ToList();
            var box = Crop.Default(Line(points));
            Assert.True(box.XMin < 2 && box.XMax > 98);                // wider than the 2nd..98th percentile
        }

        [Fact]
        public void Default_of_nothing_is_unusable()
        {
            Assert.False(Crop.Default(new List<IEnumerable<double[]>>()).IsUsable);
            Assert.False(Crop.Default(Line(new List<double[]>())).IsUsable);
        }
    }

    public class ReadRequestTests
    {
        [Fact]
        public void Parse_reads_level_and_crop()
        {
            var r = ReadRequest.Parse("{\"type\":\"readModel\",\"level\":\"Level 1\",\"crop\":{\"xmin\":0,\"ymin\":1,\"xmax\":10,\"ymax\":11}}");
            Assert.Equal("readModel", r.Type);
            Assert.Equal("Level 1", r.Level);
            Assert.NotNull(r.Crop);
            Assert.Equal((0.0, 1.0, 10.0, 11.0), (r.Crop.Value.XMin, r.Crop.Value.YMin, r.Crop.Value.XMax, r.Crop.Value.YMax));
        }

        [Fact]
        public void Parse_without_a_crop_means_everything()
        {
            Assert.Null(ReadRequest.Parse("{\"type\":\"overview\",\"level\":\"L\"}").Crop);
            Assert.Null(ReadRequest.Parse("{\"type\":\"refreshModel\"}").Level);
        }

        [Fact]
        public void Parse_normalises_an_inverted_crop()
        {
            var c = ReadRequest.Parse("{\"type\":\"readModel\",\"crop\":{\"xmin\":10,\"ymin\":11,\"xmax\":0,\"ymax\":1}}").Crop.Value;
            Assert.Equal((0.0, 1.0, 10.0, 11.0), (c.XMin, c.YMin, c.XMax, c.YMax));
        }

        [Fact]
        public void Parse_rejects_an_unknown_type_and_bad_json()
        {
            Assert.Throws<ArgumentException>(() => ReadRequest.Parse("{\"type\":\"deleteEverything\"}"));
            Assert.Throws<ArgumentException>(() => ReadRequest.Parse("not json"));
        }
    }
}
