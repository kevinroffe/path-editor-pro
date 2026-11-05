// The ribbon button: starts the engine on first use and opens (or brings forward) the path editor window.
using System;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Qbiq.PathTool.Core;

namespace Qbiq.PathTool.Addin
{
    [Transaction(TransactionMode.ReadOnly)]
    public class OpenPathToolCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            if (Session.Window != null) { Session.Window.Activate(); return Result.Succeeded; }
            try
            {
                var endpoint = Session.EnsureEngine();
                var handler = new ReadModelEvent();
                var window = new PathToolWindow(data.Application.MainWindowHandle, endpoint, ExternalEvent.Create(handler), handler);
                Session.Window = window;
                window.Show();
                return Result.Succeeded;
            }
            catch (EngineStartException e)
            {
                message = e.Message;
                return Result.Failed;
            }
            catch (Exception e)
            {
                message = "The path editor could not open: " + e.Message;
                return Result.Failed;
            }
        }
    }
}
