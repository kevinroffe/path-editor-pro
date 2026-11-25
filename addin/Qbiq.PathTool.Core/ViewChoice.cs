// Where the 3D model is read from. A 3D view the user is working in is read as it shows (hidden categories, filters, section box
// apply, as in Enscape). From any other view (a floor plan, a sheet) the whole model is read at Fine detail: falling back to the
// project's {3D} view would silently inherit whatever that view hides, such as the furniture.
namespace Qbiq.PathTool.Core
{
    public enum ViewSource { Active, WholeModel }

    public static class ViewChoice
    {
        /// <summary>What the header shows when no 3D view was used.</summary>
        public const string WholeModelName = "whole model";

        public static ViewSource Choose(bool activeIsView3D) => activeIsView3D ? ViewSource.Active : ViewSource.WholeModel;
    }
}
