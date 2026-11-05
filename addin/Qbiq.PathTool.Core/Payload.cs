// The level payload the add-in sends to the engine (backend/revit_payload.py defines the contract, schema 1).
// JSON comes from Newtonsoft.Json 13: Revit 2024 ships the same major version, so loading it inside Revit is safe.
using System.Collections.Generic;
using Newtonsoft.Json;

namespace Qbiq.PathTool.Core
{
    public class LevelInfo
    {
        [JsonProperty("name")] public string Name { get; set; } = "";
        [JsonProperty("elevation")] public double Elevation { get; set; }
    }

    public class RoomPayload
    {
        [JsonProperty("id")] public string Id { get; set; } = "";
        [JsonProperty("name")] public string Name { get; set; } = "";
        [JsonProperty("number")] public string Number { get; set; }
        [JsonProperty("polygon")] public List<double[]> Polygon { get; set; }
        [JsonProperty("area")] public double Area { get; set; }
        [JsonProperty("placed")] public bool Placed { get; set; }
        [JsonProperty("enclosed")] public bool Enclosed { get; set; }
    }

    public class MeshPayload
    {
        [JsonProperty("type")] public string Type { get; set; } = "other";
        [JsonProperty("verts")] public List<double> Verts { get; set; } = new List<double>();
        [JsonProperty("faces")] public List<int> Faces { get; set; } = new List<int>();
        [JsonProperty("color")] public string Color { get; set; }
        [JsonProperty("opacity")] public double? Opacity { get; set; }
    }

    public class LevelPayload
    {
        public const int CurrentSchema = 1;

        [JsonProperty("schema")] public int Schema { get; set; } = CurrentSchema;
        [JsonProperty("level")] public LevelInfo Level { get; set; } = new LevelInfo();
        [JsonProperty("units_to_metres")] public double UnitsToMetres { get; set; } = 1.0;
        [JsonProperty("walls")] public List<List<double[]>> Walls { get; set; } = new List<List<double[]>>();
        [JsonProperty("doors")] public List<List<double[]>> Doors { get; set; } = new List<List<double[]>>();
        [JsonProperty("windows")] public List<List<double[]>> Windows { get; set; } = new List<List<double[]>>();
        [JsonProperty("columns")] public List<List<double[]>> Columns { get; set; } = new List<List<double[]>>();
        [JsonProperty("furniture")] public List<List<double[]>> Furniture { get; set; } = new List<List<double[]>>();
        [JsonProperty("rooms")] public List<RoomPayload> Rooms { get; set; } = new List<RoomPayload>();
        [JsonProperty("meshes")] public List<MeshPayload> Meshes { get; set; } = new List<MeshPayload>();
    }

    public static class PayloadJson
    {
        public static string Serialize(LevelPayload payload) => JsonConvert.SerializeObject(payload, Formatting.None);

        public static LevelPayload Deserialize(string json) => JsonConvert.DeserializeObject<LevelPayload>(json);
    }
}
