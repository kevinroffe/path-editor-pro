// The area the user frames on the plan, and the messages the page sends the add-in about it. Coordinates are Revit model feet.
using System;
using System.Collections.Generic;
using System.Linq;
using Newtonsoft.Json.Linq;

namespace Qbiq.PathTool.Core
{
    public struct CropBox
    {
        public double XMin, YMin, XMax, YMax;

        /// <summary>The box between two corners given in any order.</summary>
        public static CropBox Normalise(double x1, double y1, double x2, double y2) => new CropBox
        {
            XMin = Math.Min(x1, x2), YMin = Math.Min(y1, y2), XMax = Math.Max(x1, x2), YMax = Math.Max(y1, y2),
        };

        /// <summary>True when another rectangle overlaps, touches or contains this box.</summary>
        public bool Intersects(double minX, double minY, double maxX, double maxY) =>
            maxX >= XMin && minX <= XMax && maxY >= YMin && minY <= YMax;

        /// <summary>A frame smaller than a square foot, or flat, is a mis-click, not an area.</summary>
        public bool IsUsable => (XMax - XMin) * (YMax - YMin) > 1.0 && XMax > XMin && YMax > YMin;
    }

    public static class Crop
    {
        const double LowPercentile = 0.02, HighPercentile = 0.98, Grow = 0.05;

        /// <summary>
        /// The area holding most of the geometry: the 2nd to 98th percentile of the vertices, grown a little, so a few far-away
        /// vertices (a site outline, a stray line) do not stretch it. Unusable for empty input.
        /// </summary>
        public static CropBox Default(IEnumerable<IEnumerable<double[]>> polylines)
        {
            var points = polylines.SelectMany(p => p).ToList();
            if (points.Count == 0) return new CropBox();
            var xs = points.Select(p => p[0]).OrderBy(v => v).ToList();
            var ys = points.Select(p => p[1]).OrderBy(v => v).ToList();
            double At(List<double> sorted, double q) => sorted[(int)Math.Round(q * (sorted.Count - 1))];
            double x0 = At(xs, LowPercentile), x1 = At(xs, HighPercentile), y0 = At(ys, LowPercentile), y1 = At(ys, HighPercentile);
            double gx = (x1 - x0) * Grow, gy = (y1 - y0) * Grow;
            return CropBox.Normalise(x0 - gx, y0 - gy, x1 + gx, y1 + gy);
        }
    }

    /// <summary>What the page asks the add-in to read: {"type": overview | readModel | refreshModel, "level": "...", "crop": {...}}.</summary>
    public sealed class ReadRequest
    {
        static readonly string[] Types = { "overview", "readModel", "refreshModel" };

        public string Type;
        public string Level;
        public CropBox? Crop;

        public static ReadRequest Parse(string json)
        {
            JObject o;
            try { o = JObject.Parse(json); }
            catch (Exception e) { throw new ArgumentException("The request is not valid JSON: " + e.Message); }
            var type = (string)o["type"];
            if (type == null || !Types.Contains(type)) throw new ArgumentException("Unknown request type '" + type + "'.");
            var request = new ReadRequest { Type = type, Level = (string)o["level"] };
            if (o["crop"] is JObject c)
                request.Crop = CropBox.Normalise((double)c["xmin"], (double)c["ymin"], (double)c["xmax"], (double)c["ymax"]);
            return request;
        }
    }
}
