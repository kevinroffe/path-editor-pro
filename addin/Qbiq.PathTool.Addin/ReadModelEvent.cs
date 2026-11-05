// Reading the Revit model must happen on Revit's main thread; an ExternalEvent is how a modeless window gets there.
// This handler reads the active view's level (else the lowest) and hands the payload JSON on; it never opens a Transaction.
using System;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Qbiq.PathTool.Addin.Extraction;
using Qbiq.PathTool.Core;

namespace Qbiq.PathTool.Addin
{
    public sealed class ReadModelEvent : IExternalEventHandler
    {
        /// <summary>Called on Revit's thread with (payload JSON or null, refresh, error text or null).</summary>
        public Action<string, bool, string> Done;
        public bool Refresh;

        public void Execute(UIApplication app)
        {
            try
            {
                var doc = app.ActiveUIDocument?.Document;
                if (doc == null) { Done?.Invoke(null, Refresh, "Open a Revit project first."); return; }
                var reader = new RevitModelReader(doc);
                var level = LevelPicker.Choose(doc.ActiveView?.GenLevel?.Name, reader.LevelNames());
                if (level == null) { Done?.Invoke(null, Refresh, "This model has no levels."); return; }
                Done?.Invoke(PayloadJson.Serialize(reader.ReadLevel(level)), Refresh, null);
            }
            catch (Exception e)
            {
                Done?.Invoke(null, Refresh, "Could not read the model: " + e.Message);
            }
        }

        public string GetName() => "Qbiq Path Tool: read model";
    }
}
