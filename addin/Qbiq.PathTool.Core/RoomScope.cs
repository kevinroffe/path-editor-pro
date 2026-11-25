// Which Revit Rooms belong to the level being read. Rooms are phase-specific and a model's rooms may sit on a level
// other than the one the walls are on, so a strict "this level, this view's phase" filter can drop every room.
using System.Collections.Generic;
using System.Linq;
using Newtonsoft.Json;

namespace Qbiq.PathTool.Core
{
    /// <summary>What the reader knows about one Room before choosing.</summary>
    public sealed class RoomCandidate
    {
        public string Id { get; set; } = "";
        /// <summary>The Room's level is the level being read.</summary>
        public bool OnLevel { get; set; }
        /// <summary>The Room's height reaches into the level being read.</summary>
        public bool InLevelBand { get; set; }
        /// <summary>The Room's phase name, or null when it has none.</summary>
        public string Phase { get; set; }
        public bool InCrop { get; set; } = true;
    }

    /// <summary>The rooms chosen and why the others were left out (sent to the engine and shown by Dump level JSON).</summary>
    public sealed class RoomScan
    {
        [JsonIgnore] public List<string> Chosen { get; set; } = new List<string>();
        [JsonProperty("total")] public int Total { get; set; }
        [JsonProperty("used")] public int Used => Chosen.Count;
        [JsonProperty("other_level")] public int OtherLevel { get; set; }
        [JsonProperty("other_phase")] public int OtherPhase { get; set; }
        [JsonProperty("outside_frame")] public int OutsideFrame { get; set; }
        [JsonProperty("phase")] public string Phase { get; set; }
        /// <summary>No room was on the level itself, so rooms reaching into it by height were used.</summary>
        [JsonProperty("by_height")] public bool ByHeight { get; set; }
        [JsonProperty("by_phase")] public Dictionary<string, int> ByPhase { get; set; } = new Dictionary<string, int>();

        public string Summary() =>
            "Rooms used " + Used + " of " + Total + (Phase != null ? " (phase " + Phase + ")" : "") + (ByHeight ? ", matched by height" : "") +
            "; other level " + OtherLevel + ", other phase " + OtherPhase + ", outside frame " + OutsideFrame;
    }

    public static class RoomScope
    {
        /// <summary>
        /// Rooms on the level (or, when none is, rooms reaching into it), in the view's phase when it has rooms there,
        /// else in the phase holding most of them; rooms outside the frame are left out last.
        /// </summary>
        public static RoomScan Choose(IReadOnlyList<RoomCandidate> rooms, string viewPhase)
        {
            var onLevel = rooms.Where(r => r.OnLevel).ToList();
            var byHeight = onLevel.Count == 0;
            if (byHeight) onLevel = rooms.Where(r => r.InLevelBand).ToList();

            var byPhase = onLevel.Where(r => r.Phase != null).GroupBy(r => r.Phase).ToDictionary(g => g.Key, g => g.Count());
            var phase = byPhase.ContainsKey(viewPhase ?? "") ? viewPhase
                : byPhase.OrderByDescending(kv => kv.Value).Select(kv => kv.Key).FirstOrDefault();
            var inPhase = onLevel.Where(r => r.Phase == null || r.Phase == phase).ToList();
            var chosen = inPhase.Where(r => r.InCrop).ToList();

            return new RoomScan
            {
                Chosen = chosen.Select(r => r.Id).ToList(),
                Total = rooms.Count,
                OtherLevel = rooms.Count - onLevel.Count,
                OtherPhase = onLevel.Count - inPhase.Count,
                OutsideFrame = inPhase.Count - chosen.Count,
                Phase = phase,
                ByHeight = byHeight && onLevel.Count > 0,
                ByPhase = byPhase,
            };
        }
    }
}
