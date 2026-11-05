using System;
using System.IO;
using Qbiq.PathTool.Core;
using Xunit;

namespace Qbiq.PathTool.Tests
{
    public class RoomChecksTests
    {
        static RoomPayload Room(bool placed = true, bool enclosed = true, double area = 100) =>
            new RoomPayload { Id = "r", Name = "Room", Placed = placed, Enclosed = enclosed, Area = area };

        [Fact] public void Unplaced_room_is_flagged() => Assert.Equal("unplaced", RoomChecks.Classify(Room(placed: false)));
        [Fact] public void Unenclosed_room_is_flagged() => Assert.Equal("unenclosed", RoomChecks.Classify(Room(enclosed: false)));
        [Fact] public void Zero_area_room_is_flagged() => Assert.Equal("zero_area", RoomChecks.Classify(Room(area: 0)));
        [Fact] public void Healthy_room_has_no_problem() => Assert.Null(RoomChecks.Classify(Room()));

        [Fact]
        public void An_unplaced_room_is_reported_as_unplaced_even_when_its_area_is_zero()
            => Assert.Equal("unplaced", RoomChecks.Classify(Room(placed: false, enclosed: false, area: 0)));
    }

    public class RecordedModelReaderTests
    {
        static RecordedModelReader Reader() => RecordedModelReader.FromJson(File.ReadAllText(PayloadTests.FixturePath()));

        [Fact]
        public void Lists_the_recorded_level()
        {
            Assert.Equal(new[] { "Level 1" }, Reader().LevelNames());
        }

        [Fact]
        public void Reads_a_recorded_level_as_the_contract_payload()
        {
            var payload = Reader().ReadLevel("Level 1");
            Assert.Equal(6, payload.Rooms.Count);
            Assert.Equal(0.3048, payload.UnitsToMetres);
        }

        [Fact]
        public void Unknown_level_names_the_available_ones()
        {
            var ex = Assert.Throws<ArgumentException>(() => Reader().ReadLevel("Nope"));
            Assert.Contains("Level 1", ex.Message);
        }
    }
}
