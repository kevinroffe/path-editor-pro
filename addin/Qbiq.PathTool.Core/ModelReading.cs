// What the window needs from a model source: the level names, a quick overview of one level (to frame the area), and the
// full read of one level inside the framed area. RevitModelReader (in the add-in) reads a live Revit document;
// RecordedModelReader replays a saved payload so everything downstream can be developed and tested without Revit.
using System;
using System.Collections.Generic;
using System.Linq;

namespace Qbiq.PathTool.Core
{
    public interface IModelReader
    {
        IReadOnlyList<string> LevelNames();

        /// <summary>One level, uncropped, 2D only (no meshes): what the page shows while the user frames the area.</summary>
        LevelPayload ReadOverview(string levelName);

        /// <summary>One level inside the crop (or all of it when null): its 2D elements and, when asked, the 3D meshes.</summary>
        LevelPayload ReadModel(string levelName, CropBox? crop, bool includeMeshes);
    }

    /// <summary>A read that cannot be done, with a message the user can act on (shown as it is).</summary>
    public class ModelReadException : Exception
    {
        public ModelReadException(string message) : base(message) { }
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

        LevelPayload Copy(string levelName)
        {
            if (levelName != payload.Level.Name)
                throw new ArgumentException("No level '" + levelName + "' in the recording; available: " + string.Join(", ", LevelNames()));
            var copy = PayloadJson.Deserialize(PayloadJson.Serialize(payload));
            copy.Levels = LevelNames().ToList();
            copy.CurrentLevel = payload.Level.Name;
            return copy;
        }

        /// <summary>The whole level, uncropped, with its meshes.</summary>
        public LevelPayload ReadLevel(string levelName) => ReadModel(levelName, null, true);

        public LevelPayload ReadOverview(string levelName)
        {
            var p = Copy(levelName);
            p.Meshes.Clear();
            p.Overview = true;
            p.CropDefault = CropRect.From(Crop.Default(p.Walls));
            return p;
        }

        public LevelPayload ReadModel(string levelName, CropBox? crop, bool includeMeshes)
        {
            var p = Copy(levelName);
            if (crop.HasValue)
            {
                var c = crop.Value;
                bool Touches(List<double[]> line) => line.Count > 0 &&
                    c.Intersects(line.Min(v => v[0]), line.Min(v => v[1]), line.Max(v => v[0]), line.Max(v => v[1]));
                p.Walls = p.Walls.Where(Touches).ToList();
                p.Doors = p.Doors.Where(Touches).ToList();
                p.Windows = p.Windows.Where(Touches).ToList();
                p.Columns = p.Columns.Where(Touches).ToList();
                p.Furniture = p.Furniture.Where(Touches).ToList();
                p.Rooms = p.Rooms.Where(r => r.Polygon == null || Touches(r.Polygon)).ToList();
            }
            if (!includeMeshes) { p.Meshes.Clear(); p.KeepMeshes = true; }
            return p;
        }
    }

    public static class LevelPicker
    {
        /// <summary>The level to read: the active view's level when the model has it, else the lowest (names are in elevation order); null if none.</summary>
        public static string Choose(string activeViewLevel, IReadOnlyList<string> levelNames)
        {
            if (levelNames.Count == 0) return null;
            return activeViewLevel != null && levelNames.Contains(activeViewLevel) ? activeViewLevel : levelNames[0];
        }
    }
}
