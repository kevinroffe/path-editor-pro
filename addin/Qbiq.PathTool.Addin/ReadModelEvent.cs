// Reading the Revit model must happen on Revit's main thread; an ExternalEvent is how a modeless window gets there.
// The page's request says what to read: a quick overview (to frame the area), the model inside the framed area, a level
// change (2D only, keeping the 3D), or a refresh (same level and area as last time). Never opens a Transaction.
using System;
using System.Linq;
using Autodesk.Revit.UI;
using Qbiq.PathTool.Addin.Extraction;
using Qbiq.PathTool.Core;

namespace Qbiq.PathTool.Addin
{
    public sealed class ReadModelEvent : IExternalEventHandler
    {
        /// <summary>Called on Revit's thread with (payload or null, refresh, error text or null). Serialising is left to the caller so it runs off Revit's thread.</summary>
        public Action<LevelPayload, bool, string> Done;

        /// <summary>What to read; set before the event is raised.</summary>
        public ReadRequest Request = new ReadRequest { Type = "overview" };

        string lastLevel;
        CropBox? lastCrop;
        bool wantMeshes;             // the user has the Top view open: refreshes read the 3D too

        bool Refresh => Request.Type == "refreshModel";

        public void Execute(UIApplication app)
        {
            try
            {
                var doc = app.ActiveUIDocument?.Document;
                if (doc == null) { Done?.Invoke(null, Refresh, "Open a Revit project first."); return; }
                var reader = new RevitModelReader(doc);
                var names = reader.LevelNames();
                var level = Pick(Request.Level, names) ?? Pick(lastLevel, names) ?? LevelPicker.Choose(doc.ActiveView?.GenLevel?.Name, names);
                if (level == null) { Done?.Invoke(null, Refresh, "This model has no levels."); return; }

                LevelPayload payload;
                switch (Request.Type)
                {
                    case "overview":
                        payload = reader.ReadOverview(level);
                        lastLevel = level;
                        break;
                    case "readModel":
                        lastLevel = level;
                        lastCrop = Request.Crop;
                        if (Request.Meshes) wantMeshes = true;                // Top view asked for the 3D
                        payload = reader.ReadModel(level, lastCrop, Request.Meshes && !Request.KeepMeshes);
                        break;
                    default:                                                  // refreshModel: same level and area again, 3D only if the Top view is open
                        lastLevel = level;
                        payload = reader.ReadModel(level, lastCrop, wantMeshes);
                        break;
                }
                Done?.Invoke(payload, Refresh, null);
            }
            catch (ModelReadException e)
            {
                Done?.Invoke(null, Refresh, e.Message);
            }
            catch (Exception e)
            {
                Done?.Invoke(null, Refresh, "Could not read the model: " + e.Message);
            }
        }

        static string Pick(string wanted, System.Collections.Generic.IReadOnlyList<string> names) =>
            wanted != null && names.Contains(wanted) ? wanted : null;

        public string GetName() => "Qbiq Path Tool: read model";
    }
}
