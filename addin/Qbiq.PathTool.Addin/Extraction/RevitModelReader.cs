// Reads the open Revit model as the contract payload (see Qbiq.PathTool.Core/Payload.cs).
// Read-only: no Transaction is ever opened. Coordinates are Revit's internal units (feet) and internal origin.
//   2D (plan, routing): one level, elements whose height reaches into it, inside the crop.
//   3D: the whole building through the active Revit 3D view (as Enscape renders it), inside the crop.
// Version-one scope: the active view's phase, the primary design option; linked models are ignored.
using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Architecture;
using Qbiq.PathTool.Core;

namespace Qbiq.PathTool.Addin.Extraction
{
    public sealed class RevitModelReader : IModelReader
    {
        public const double FeetToMetres = 0.3048;
        const double DefaultOpeningWidthFt = 3.0;
        const double Far = 1e7;               // "unbounded" in feet for the outline filters

        readonly Document doc;
        LevelBand band;                       // the height band of the level being read (see OnLevel)
        CropBox? crop;                        // the area being read, or null for everything

        public RevitModelReader(Document doc) { this.doc = doc; }

        public IReadOnlyList<string> LevelNames() =>
            new FilteredElementCollector(doc).OfClass(typeof(Level)).Cast<Level>()
                .OrderBy(l => l.Elevation).Select(l => l.Name).ToList();

        /// <summary>The whole level with its 3D: for the diagnostics button.</summary>
        public LevelPayload ReadLevel(string levelName) => ReadModel(levelName, null, true);

        /// <summary>One level, uncropped and without 3D: what the page shows while the user frames the area.</summary>
        public LevelPayload ReadOverview(string levelName)
        {
            var payload = Read2D(levelName, null);
            payload.Overview = true;
            payload.CropDefault = CropRect.From(Crop.Default(payload.Walls));
            return payload;
        }

        public LevelPayload ReadModel(string levelName, CropBox? area, bool includeMeshes)
        {
            var payload = Read2D(levelName, area);
            if (includeMeshes)
            {
                var view = Find3DView();
                payload.ViewName = view.Name;
                payload.Meshes = new MeshReader(doc, view).Read(area);
            }
            else payload.KeepMeshes = true;
            return payload;
        }

        // ---- the 3D view ----

        View3D Find3DView()
        {
            var all = new FilteredElementCollector(doc).OfClass(typeof(View3D)).Cast<View3D>().Where(v => !v.IsTemplate).ToList();
            var active = doc.ActiveView as View3D;
            // A perspective camera view cannot be read the way a parallel 3D view can (geometry and collectors by view), so
            // such a view falls back to the project's {3D}; the header shows which view was used.
            var usable = active != null && !active.IsTemplate && !active.IsPerspective;
            switch (ViewChoice.Choose(usable, all.Where(v => !v.IsPerspective).Select(v => v.Name).ToList()))
            {
                case ViewSource.Active: return active;
                case ViewSource.Default: return all.First(v => v.Name == ViewChoice.DefaultViewName);
                default: throw new ModelReadException(ViewChoice.NoViewMessage);
            }
        }

        // ---- the 2D plan of one level ----

        LevelPayload Read2D(string levelName, CropBox? area)
        {
            var level = new FilteredElementCollector(doc).OfClass(typeof(Level)).Cast<Level>()
                .FirstOrDefault(l => l.Name == levelName);
            if (level == null)
                throw new ModelReadException("No level '" + levelName + "' in this model; available: " + string.Join(", ", LevelNames()));

            var phase = ActivePhase();
            crop = area;
            band = LevelBand.For(level.Elevation,
                new FilteredElementCollector(doc).OfClass(typeof(Level)).Cast<Level>().Select(l => l.Elevation).ToList());
            var payload = new LevelPayload
            {
                Level = new LevelInfo { Name = level.Name, Elevation = level.Elevation },
                UnitsToMetres = FeetToMetres,
                Levels = LevelNames().ToList(),
                CurrentLevel = level.Name,
            };

            foreach (var wall in OnLevel(BuiltInCategory.OST_Walls, phase).OfType<Wall>())
            {
                var curve = (wall.Location as LocationCurve)?.Curve;
                if (curve != null) payload.Walls.Add(Polyline(curve.Tessellate()));
            }
            foreach (var door in OnLevel(BuiltInCategory.OST_Doors, phase).OfType<FamilyInstance>())
                AddOpening(payload.Doors, door, BuiltInParameter.DOOR_WIDTH);
            foreach (var window in OnLevel(BuiltInCategory.OST_Windows, phase).OfType<FamilyInstance>())
                AddOpening(payload.Windows, window, BuiltInParameter.WINDOW_WIDTH);
            foreach (var cat in new[] { BuiltInCategory.OST_Columns, BuiltInCategory.OST_StructuralColumns })
                foreach (var column in OnLevel(cat, phase)) AddBox(payload.Columns, column);
            foreach (var cat in new[] { BuiltInCategory.OST_Furniture, BuiltInCategory.OST_FurnitureSystems, BuiltInCategory.OST_Casework })
                foreach (var item in OnLevel(cat, phase)) AddBox(payload.Furniture, item);

            var options = new SpatialElementBoundaryOptions();
            foreach (var room in new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms)
                         .WhereElementIsNotElementType().OfType<Room>()
                         .Where(r => r.LevelId == level.Id && InScope(r, phase) && InCrop(r)))
                payload.Rooms.Add(ReadRoom(room, options));

            return payload;
        }

        // ---- scope: phase, design option, crop ----

        ElementId ActivePhase()
        {
            var fromView = doc.ActiveView?.get_Parameter(BuiltInParameter.VIEW_PHASE)?.AsElementId();
            if (fromView != null && fromView != ElementId.InvalidElementId) return fromView;
            return doc.Phases.Size == 0 ? ElementId.InvalidElementId : doc.Phases.get_Item(doc.Phases.Size - 1).Id;
        }

        static bool InScope(Element e, ElementId phase)
        {
            if (e.DesignOption != null && !e.DesignOption.IsPrimary) return false;
            if (phase == ElementId.InvalidElementId) return true;
            try
            {
                var status = e.GetPhaseStatus(phase);
                return status == ElementOnPhaseStatus.Existing || status == ElementOnPhaseStatus.New
                    || status == ElementOnPhaseStatus.Temporary;
            }
            catch (Exception) { return true; }       // elements without a phase are always in scope
        }

        /// <summary>A room is in the crop when its box touches it; an unplaced room has no position and is kept so it can be reported.</summary>
        bool InCrop(Element e)
        {
            if (!crop.HasValue) return true;
            var box = e.get_BoundingBox(null);
            return box == null || crop.Value.Intersects(box.Min.X, box.Min.Y, box.Max.X, box.Max.Y);
        }

        /// <summary>
        /// Elements belong to every level their height reaches into: a facade or core wall whose base is Level 1 and top is Level 5
        /// must appear when Level 3 is read. Inside the crop (all heights of the level band) when there is one.
        /// </summary>
        IEnumerable<Element> OnLevel(BuiltInCategory category, ElementId phase)
        {
            var xy = crop.HasValue ? new[] { crop.Value.XMin, crop.Value.YMin, crop.Value.XMax, crop.Value.YMax } : new[] { -Far, -Far, Far, Far };
            return new FilteredElementCollector(doc).OfCategory(category).WhereElementIsNotElementType()
                .WherePasses(new BoundingBoxIntersectsFilter(new Outline(new XYZ(xy[0], xy[1], band.Low), new XYZ(xy[2], xy[3], band.High))))
                .Where(e => InScope(e, phase));
        }

        // ---- geometry to polylines ----

        static double[] Pt(XYZ p) => new[] { p.X, p.Y };

        static List<double[]> Polyline(IEnumerable<XYZ> points) => points.Select(Pt).ToList();

        static void AddBox(List<List<double[]>> into, Element e)
        {
            var box = e.get_BoundingBox(null);
            if (box == null) return;
            into.Add(new List<double[]>
            {
                new[] { box.Min.X, box.Min.Y }, new[] { box.Max.X, box.Min.Y },
                new[] { box.Max.X, box.Max.Y }, new[] { box.Min.X, box.Max.Y }, new[] { box.Min.X, box.Min.Y },
            });
        }

        /// <summary>The opening as a segment across its host wall, centred on the family instance.</summary>
        static void AddOpening(List<List<double[]>> into, FamilyInstance fi, BuiltInParameter widthParameter)
        {
            var at = (fi.Location as LocationPoint)?.Point;
            if (at == null) return;
            var width = (fi.get_Parameter(widthParameter) ?? fi.Symbol?.get_Parameter(widthParameter))?.AsDouble() ?? 0;
            if (width <= 0) width = DefaultOpeningWidthFt;

            var along = XYZ.BasisX;
            var curve = ((fi.Host as Wall)?.Location as LocationCurve)?.Curve;
            if (curve != null)
            {
                var projection = curve.Project(at);
                if (projection != null)
                {
                    var tangent = curve.ComputeDerivatives(projection.Parameter, false).BasisX;
                    if (tangent.GetLength() > 1e-9) along = tangent.Normalize();
                }
            }
            var half = along * (width / 2);
            into.Add(new List<double[]> { Pt(at - half), Pt(at + half) });
        }

        // ---- rooms ----

        static RoomPayload ReadRoom(Room room, SpatialElementBoundaryOptions options)
        {
            var payload = new RoomPayload
            {
                Id = room.UniqueId,
                Name = room.get_Parameter(BuiltInParameter.ROOM_NAME)?.AsString() ?? "",
                Number = room.Number,
                Area = room.Area,
                Placed = room.Location != null,
            };
            if (payload.Placed && room.Area > 0)
            {
                // The outer loop only; holes (columns, shafts inside the room) are left out in version one.
                var loops = room.GetBoundarySegments(options);
                if (loops != null && loops.Count > 0)
                {
                    var outer = new List<double[]>();
                    foreach (var segment in loops[0])
                        foreach (var p in segment.GetCurve().Tessellate())
                            if (outer.Count == 0 || outer[outer.Count - 1][0] != p.X || outer[outer.Count - 1][1] != p.Y) outer.Add(Pt(p));
                    if (outer.Count >= 3)
                    {
                        payload.Polygon = outer;
                        payload.Enclosed = true;
                    }
                }
            }
            return payload;
        }
    }
}
