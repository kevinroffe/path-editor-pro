// Which Revit 3D view the model is read through. Enscape renders the active 3D view, so the tool reads the same one:
// hidden categories, view filters and the section box then apply exactly as they do there.
using System.Collections.Generic;
using System.Linq;

namespace Qbiq.PathTool.Core
{
    public enum ViewSource { Active, Default, None }

    public static class ViewChoice
    {
        public const string DefaultViewName = "{3D}";

        public const string NoViewMessage =
            "Open a 3D view in Revit and try again. The path tool takes its 3D model from the active 3D view, as Enscape does.";

        /// <summary>The active view when it is a 3D view; else the project's default 3D view if it has one; else none.</summary>
        public static ViewSource Choose(bool activeIsView3D, IReadOnlyList<string> view3DNames, string defaultName = DefaultViewName)
        {
            if (activeIsView3D) return ViewSource.Active;
            return defaultName != null && view3DNames.Contains(defaultName) ? ViewSource.Default : ViewSource.None;
        }
    }
}
