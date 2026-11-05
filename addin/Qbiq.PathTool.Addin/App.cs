// Revit entry point: adds the "Path Tool" ribbon tab and stops the engine when Revit closes.
using System;
using System.Reflection;
using Autodesk.Revit.UI;

namespace Qbiq.PathTool.Addin
{
    public class App : IExternalApplication
    {
        const string TabName = "Path Tool";

        public Result OnStartup(UIControlledApplication application)
        {
            try { application.CreateRibbonTab(TabName); }
            catch (ArgumentException) { /* the tab already exists */ }

            var panel = application.CreateRibbonPanel(TabName, "Path Tool");
            var assembly = Assembly.GetExecutingAssembly().Location;
            panel.AddItem(new PushButtonData("QbiqOpenPathTool", "Open Path\nTool", assembly, typeof(OpenPathToolCommand).FullName)
            {
                ToolTip = "Open the path editor with this model: Auto-path, edit path, video timeline.",
            });
            // A separate panel, so the check is not mistaken for part of the tool itself.
            var diagnostics = application.CreateRibbonPanel(TabName, "Diagnostics");
            diagnostics.AddItem(new PushButtonData("QbiqDumpLevel", "Dump level\nJSON", assembly, typeof(DumpLevelCommand).FullName)
            {
                ToolTip = "Check the extraction: writes the current level as the payload JSON the path editor reads.",
            });
            return Result.Succeeded;
        }

        public Result OnShutdown(UIControlledApplication application)
        {
            Session.Shutdown();
            return Result.Succeeded;
        }
    }
}
