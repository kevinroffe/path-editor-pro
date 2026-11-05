// EXPERIMENTAL "Revit camera" preview: moves the active Revit 3D view's camera along the path as the page plays.
// Changing a view's orientation edits the document, so each move runs in a short Transaction (named so it is easy to spot in
// Undo); that is the price of this spike and is reported to the page if Revit refuses. The orientation the view had before is
// restored when the preview stops or the window closes. The latest pose wins: Raise() calls that pile up become one move.
using System;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Qbiq.PathTool.Core;

namespace Qbiq.PathTool.Addin
{
    public sealed class CameraEvent : IExternalEventHandler
    {
        const double EyeHeightFt = 1.57 / 0.3048;       // the same eye height the exported path uses

        /// <summary>Called on Revit's thread when the preview cannot run or stops itself: (message).</summary>
        public Action<string> Failed;

        readonly object gate = new object();
        CameraMessage pending;
        ViewOrientation3D saved;
        ElementId savedView;
        bool running;

        /// <summary>Set the next thing to do (start, a pose, or stop) before raising the event; the latest message wins.</summary>
        public void Set(CameraMessage message)
        {
            lock (gate)
            {
                // a stop must not be overwritten by a late pose, and a pose must not hide a start that has not run yet
                if (pending != null && pending.Type == "cameraStop" && message.Type == "camera") return;
                if (pending != null && pending.Type == "cameraStart" && message.Type == "camera") return;
                pending = message;
            }
        }

        public void Execute(UIApplication app)
        {
            CameraMessage m;
            lock (gate) { m = pending; pending = null; }
            if (m == null) return;
            try
            {
                var uidoc = app.ActiveUIDocument;
                if (uidoc == null) { Fail("Open a Revit project first."); return; }
                switch (m.Type)
                {
                    case "cameraStart": Start(uidoc); break;
                    case "cameraStop": Stop(uidoc.Document); break;
                    default: Move(uidoc, m); break;
                }
            }
            catch (Exception e)
            {
                running = false;
                Fail("The Revit camera could not be moved: " + e.Message);
            }
        }

        void Start(UIDocument uidoc)
        {
            var view = uidoc.ActiveView as View3D;
            if (view == null) { Fail("Make a 3D view the active Revit view first (Enscape uses one too)."); return; }
            if (view.IsLocked) { Fail("The active 3D view is locked. Unlock it, or open another 3D view."); return; }
            if (!view.IsPerspective) { Fail("The active 3D view is isometric. Use a perspective view (the camera icon in the 3D view's toolbar)."); return; }
            saved = view.GetOrientation();
            savedView = view.Id;
            running = true;
        }

        void Move(UIDocument uidoc, CameraMessage m)
        {
            if (!running) return;                                            // a pose that arrives after the preview stopped
            var view = uidoc.ActiveView as View3D;
            if (view == null || view.Id != savedView) { running = false; Fail("The active view changed, so the Revit camera preview stopped."); return; }
            var pose = CameraPose.FromPage(m.X, m.Y, m.Yaw, m.Elevation, EyeHeightFt);
            Apply(uidoc.Document, view, new ViewOrientation3D(ToXyz(pose.Eye), ToXyz(pose.Up), ToXyz(pose.Forward)));
            uidoc.RefreshActiveView();
        }

        void Stop(Document doc)
        {
            if (!running) return;
            running = false;
            var view = doc.GetElement(savedView) as View3D;
            if (view != null && saved != null) Apply(doc, view, saved);
            saved = null;
        }

        static void Apply(Document doc, View3D view, ViewOrientation3D orientation)
        {
            using (var t = new Transaction(doc, "Path Tool: preview camera"))
            {
                t.Start();
                view.SetOrientation(orientation);
                t.Commit();
            }
        }

        static XYZ ToXyz(double[] v) => new XYZ(v[0], v[1], v[2]);

        void Fail(string message) => Failed?.Invoke(message);

        public string GetName() => "Qbiq Path Tool: Revit camera";
    }
}
