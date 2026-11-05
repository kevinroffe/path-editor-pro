using System;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using Qbiq.PathTool.Core;
using Xunit;

namespace Qbiq.PathTool.Tests
{
    public class PayloadTests
    {
        // The contract fixture lives with the engine's tests: both sides must agree on it.
        public static string FixturePath()
        {
            var dir = new DirectoryInfo(AppContext.BaseDirectory);
            while (dir != null && !File.Exists(Path.Combine(dir.FullName, "backend", "tests", "fixtures", "revit_level.json")))
                dir = dir.Parent;
            Assert.NotNull(dir);
            return Path.Combine(dir.FullName, "backend", "tests", "fixtures", "revit_level.json");
        }

        // 20 and 20.0 are the same JSON number but different token types to Newtonsoft; compare them as numbers.
        static JToken Numbers(JToken token)
        {
            foreach (var v in ((JContainer)token).DescendantsAndSelf().OfType<JValue>().Where(x => x.Type == JTokenType.Integer))
                v.Value = Convert.ToDouble(v.Value);
            return token;
        }

        [Fact]
        public void Golden_fixture_round_trips_identically()
        {
            var original = File.ReadAllText(FixturePath());
            var payload = PayloadJson.Deserialize(original);
            Assert.Equal(1, payload.Schema);
            Assert.Equal("Level 1", payload.Level.Name);
            Assert.Equal(0.3048, payload.UnitsToMetres);
            Assert.Equal(6, payload.Rooms.Count);
            Assert.Single(payload.Meshes);
            var again = PayloadJson.Serialize(payload);
            Assert.True(JToken.DeepEquals(Numbers(JToken.Parse(original)), Numbers(JToken.Parse(again))),
                "serialized payload differs from the contract fixture");
        }

        [Fact]
        public void Non_ascii_room_name_survives()
        {
            var payload = PayloadJson.Deserialize(File.ReadAllText(FixturePath()));
            payload.Rooms[1].Name = "Café Lounge";
            var back = PayloadJson.Deserialize(PayloadJson.Serialize(payload));
            Assert.Equal("Café Lounge", back.Rooms[1].Name);
        }

        [Fact]
        public void Missing_optional_fields_become_empty_lists()
        {
            var payload = PayloadJson.Deserialize(
                "{\"schema\":1,\"level\":{\"name\":\"L\",\"elevation\":0},\"units_to_metres\":0.3048,\"walls\":[[[0,0],[1,0]]]}");
            Assert.Single(payload.Walls);
            Assert.Empty(payload.Doors);
            Assert.Empty(payload.Windows);
            Assert.Empty(payload.Columns);
            Assert.Empty(payload.Furniture);
            Assert.Empty(payload.Rooms);
            Assert.Empty(payload.Meshes);
        }
    }
}
