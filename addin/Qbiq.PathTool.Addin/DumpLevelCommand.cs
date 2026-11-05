// Developer check for the extraction: writes the active level as the payload JSON and shows the counts.
using System;
using System.IO;
using System.Linq;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Qbiq.PathTool.Addin.Extraction;
using Qbiq.PathTool.Core;

namespace Qbiq.PathTool.Addin
{
    [Transaction(TransactionMode.ReadOnly)]
    public class DumpLevelCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            try
            {
                var doc = data.Application.ActiveUIDocument.Document;
                var reader = new RevitModelReader(doc);
                var level = LevelPicker.Choose(doc.ActiveView?.GenLevel?.Name, reader.LevelNames());
                if (level == null) { message = "This model has no levels."; return Result.Failed; }

                var payload = reader.ReadLevel(level);
                var path = Path.Combine(Path.GetTempPath(), "qbiq-level-" + string.Concat(level.Select(c => char.IsLetterOrDigit(c) ? c : '_')) + ".json");
                File.WriteAllText(path, PayloadJson.Serialize(payload));

                var problems = payload.Rooms.Count(r => RoomChecks.Classify(r) != null);
                TaskDialog.Show("Qbiq Path Tool", "Level: " + level + "\n" +
                    "Walls " + payload.Walls.Count + ", doors " + payload.Doors.Count + ", windows " + payload.Windows.Count + ",\n" +
                    "columns " + payload.Columns.Count + ", furniture " + payload.Furniture.Count + "\n" +
                    "Rooms " + payload.Rooms.Count + " (" + problems + " with problems)\n" +
                    "Meshes " + payload.Meshes.Count + ", vertices " + payload.Meshes.Sum(m => m.Verts.Count / 3) + "\n\n" + path);
                return Result.Succeeded;
            }
            catch (Exception e)
            {
                message = e.Message;
                return Result.Failed;
            }
        }
    }
}
