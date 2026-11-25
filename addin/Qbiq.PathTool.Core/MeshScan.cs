// How the 3D read went per mesh type: how many elements gave geometry, how many only at Fine detail, how many gave none or failed.
using System.Collections.Generic;
using System.Linq;
using Newtonsoft.Json;

namespace Qbiq.PathTool.Core
{
    public enum MeshOutcome { Read, ReadAtFine, Empty, Failed }

    public sealed class TypeCount
    {
        [JsonProperty("elements")] public int Elements { get; set; }
        [JsonProperty("read")] public int Read { get; set; }
        /// <summary>Gave nothing with the view's settings, but did at Fine detail.</summary>
        [JsonProperty("read_at_fine")] public int ReadAtFine { get; set; }
        [JsonProperty("empty")] public int Empty { get; set; }
        [JsonProperty("failed")] public int Failed { get; set; }

        public int[] ToArray() => new[] { Elements, Read, ReadAtFine, Empty, Failed };
    }

    public sealed class MeshScan
    {
        [JsonProperty("types")] public SortedDictionary<string, TypeCount> Types { get; } = new SortedDictionary<string, TypeCount>();

        public void Count(string type, MeshOutcome outcome)
        {
            if (!Types.TryGetValue(type, out var c)) Types[type] = c = new TypeCount();
            c.Elements++;
            switch (outcome)
            {
                case MeshOutcome.Read: c.Read++; break;
                case MeshOutcome.ReadAtFine: c.Read++; c.ReadAtFine++; break;
                case MeshOutcome.Empty: c.Empty++; break;
                default: c.Failed++; break;
            }
        }

        public string Summary() => "3D: " + string.Join(", ", Types.Select(kv => kv.Key + " " + kv.Value.Read + "/" + kv.Value.Elements +
            Detail(kv.Value)));

        static string Detail(TypeCount c)
        {
            var parts = new List<string>();
            if (c.ReadAtFine > 0) parts.Add(c.ReadAtFine + " only at Fine");
            if (c.Empty > 0) parts.Add(c.Empty + " empty");
            if (c.Failed > 0) parts.Add(c.Failed + " failed");
            return parts.Count == 0 ? "" : " (" + string.Join(", ", parts) + ")";
        }
    }
}
