// The "Revit camera" preview: the page sends where the camera is along the path (plan position and yaw), and the add-in
// moves the active Revit 3D view's camera there. These are the pure parts: the pose in Revit terms and the message format.
using System;
using Newtonsoft.Json.Linq;

namespace Qbiq.PathTool.Core
{
    /// <summary>An eye point and view directions in Revit model feet (Z up).</summary>
    public sealed class CameraPose
    {
        public double[] Eye, Forward, Up;

        /// <summary>
        /// The page's plan space has y negated and yaw measured as (cos, sin) in that space, so a plan yaw of 90 looks toward -y in
        /// Revit. The view stays level. The eye is at the level's height plus the eye height.
        /// </summary>
        public static CameraPose FromPage(double xFt, double yDisplayFt, double yawDeg, double levelElevationFt, double eyeHeightFt)
        {
            var yaw = yawDeg * Math.PI / 180.0;
            return new CameraPose
            {
                Eye = new[] { xFt, -yDisplayFt, levelElevationFt + eyeHeightFt },
                Forward = new[] { Math.Cos(yaw), -Math.Sin(yaw), 0.0 },
                Up = new[] { 0.0, 0.0, 1.0 },
            };
        }
    }

    /// <summary>A message from the page about the camera preview: camera (a pose), cameraStart or cameraStop.</summary>
    public sealed class CameraMessage
    {
        public string Type;
        public double X, Y, Yaw, Elevation;

        public static bool TryParse(string json, out CameraMessage message)
        {
            message = null;
            try
            {
                var o = JObject.Parse(json);
                var type = (string)o["type"];
                if (type == "cameraStart" || type == "cameraStop") { message = new CameraMessage { Type = type }; return true; }
                if (type != "camera" || o["x"] == null || o["y"] == null || o["yaw"] == null) return false;
                if (o["x"].Type != JTokenType.Float && o["x"].Type != JTokenType.Integer) return false;
                if (o["y"].Type != JTokenType.Float && o["y"].Type != JTokenType.Integer) return false;
                if (o["yaw"].Type != JTokenType.Float && o["yaw"].Type != JTokenType.Integer) return false;
                var m = new CameraMessage { Type = type, X = (double)o["x"], Y = (double)o["y"], Yaw = (double)o["yaw"], Elevation = (double?)o["elevation"] ?? 0 };
                if (double.IsNaN(m.X) || double.IsInfinity(m.X) || double.IsNaN(m.Y) || double.IsInfinity(m.Y)
                    || double.IsNaN(m.Yaw) || double.IsInfinity(m.Yaw) || double.IsNaN(m.Elevation) || double.IsInfinity(m.Elevation)) return false;
                message = m;
                return true;
            }
            catch (Exception)                                                   // not JSON, or a number that does not fit
            {
                return false;
            }
        }
    }
}
