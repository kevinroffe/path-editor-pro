// What the window needs from a model source: the level names, and one level as the contract payload.
// RevitModelReader (in the add-in) reads a live Revit document; RecordedModelReader replays a saved payload so
// everything downstream can be developed and tested without Revit.
using System;
using System.Collections.Generic;
using System.Linq;

namespace Qbiq.PathTool.Core
{
    public interface IModelReader
    {
        IReadOnlyList<string> LevelNames();
        LevelPayload ReadLevel(string levelName);
    }

    public static class RoomChecks
    {
        /// <summary>"unplaced", "unenclosed", "zero_area", or null for a usable room.</summary>
        public static string Classify(RoomPayload room)
        {
            if (!room.Placed) return "unplaced";
            if (!room.Enclosed) return "unenclosed";
            if (room.Area <= 0) return "zero_area";
            return null;
        }
    }

    public sealed class RecordedModelReader : IModelReader
    {
        readonly LevelPayload payload;

        RecordedModelReader(LevelPayload payload) { this.payload = payload; }

        public static RecordedModelReader FromJson(string json) => new RecordedModelReader(PayloadJson.Deserialize(json));

        public IReadOnlyList<string> LevelNames() => new[] { payload.Level.Name };

        public LevelPayload ReadLevel(string levelName)
        {
            if (levelName != payload.Level.Name)
                throw new ArgumentException("No level '" + levelName + "' in the recording; available: " + string.Join(", ", LevelNames()));
            return payload;
        }
    }
}
