using System.Collections.Generic;
using System.Linq;
using Qbiq.PathTool.Core;
using Xunit;

namespace Qbiq.PathTool.Tests
{
    public class RoomScopeTests
    {
        static RoomCandidate Room(string id, bool onLevel = true, bool inBand = true, string phase = "New Construction", bool inCrop = true) =>
            new RoomCandidate { Id = id, OnLevel = onLevel, InLevelBand = inBand, Phase = phase, InCrop = inCrop };

        static List<string> Ids(RoomScan scan) => scan.Chosen.OrderBy(i => i).ToList();

        [Fact]
        public void Rooms_on_the_level_in_the_views_phase_are_used()
        {
            var scan = RoomScope.Choose(new[] { Room("a"), Room("b"), Room("c", onLevel: false, inBand: false) }, "New Construction");
            Assert.Equal(new[] { "a", "b" }, Ids(scan));
            Assert.Equal(1, scan.OtherLevel);
            Assert.Equal("New Construction", scan.Phase);
        }

        [Fact]
        public void Rooms_only_in_another_phase_are_used_with_that_phase()
        {
            var scan = RoomScope.Choose(new[] { Room("a", phase: "Existing"), Room("b", phase: "Existing") }, "New Construction");
            Assert.Equal(new[] { "a", "b" }, Ids(scan));
            Assert.Equal("Existing", scan.Phase);
            Assert.Equal(0, scan.OtherPhase);
        }

        [Fact]
        public void With_rooms_in_several_phases_the_views_phase_wins()
        {
            var scan = RoomScope.Choose(new[] { Room("a", phase: "Existing"), Room("b", phase: "Existing"), Room("c") }, "New Construction");
            Assert.Equal(new[] { "c" }, Ids(scan));
            Assert.Equal(2, scan.OtherPhase);
        }

        [Fact]
        public void Without_the_views_phase_the_phase_with_most_rooms_wins()
        {
            var scan = RoomScope.Choose(new[] { Room("a", phase: "Phase 1"), Room("b", phase: "Phase 2"), Room("c", phase: "Phase 2") }, "New Construction");
            Assert.Equal(new[] { "b", "c" }, Ids(scan));
            Assert.Equal("Phase 2", scan.Phase);
        }

        [Fact]
        public void Rooms_without_a_phase_are_always_kept()
        {
            var scan = RoomScope.Choose(new[] { Room("a"), Room("b", phase: null) }, "New Construction");
            Assert.Equal(new[] { "a", "b" }, Ids(scan));
        }

        [Fact]
        public void When_no_room_is_on_the_level_rooms_reaching_into_it_are_used()
        {
            var scan = RoomScope.Choose(new[] { Room("a", onLevel: false), Room("b", onLevel: false, inBand: false) }, "New Construction");
            Assert.Equal(new[] { "a" }, Ids(scan));
            Assert.True(scan.ByHeight);
        }

        [Fact]
        public void Rooms_reaching_into_the_level_are_not_used_when_some_are_on_it()
        {
            var scan = RoomScope.Choose(new[] { Room("a"), Room("b", onLevel: false) }, "New Construction");
            Assert.Equal(new[] { "a" }, Ids(scan));
            Assert.False(scan.ByHeight);
        }

        [Fact]
        public void Rooms_outside_the_frame_are_counted_and_left_out()
        {
            var scan = RoomScope.Choose(new[] { Room("a"), Room("b", inCrop: false) }, "New Construction");
            Assert.Equal(new[] { "a" }, Ids(scan));
            Assert.Equal(1, scan.OutsideFrame);
            Assert.Equal(2, scan.Total);
        }

        [Fact]
        public void No_rooms_gives_an_empty_scan()
        {
            var scan = RoomScope.Choose(new RoomCandidate[0], "New Construction");
            Assert.Empty(scan.Chosen);
            Assert.Null(scan.Phase);
        }
    }
}
