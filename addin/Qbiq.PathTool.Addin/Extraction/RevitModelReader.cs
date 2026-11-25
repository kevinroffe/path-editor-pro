// Reads the open Revit model as the contract payload (see Qbiq.PathTool.Core/Payload.cs).
// Read-only: no Transaction is ever opened. Coordinates are Revit's internal units (feet) and internal origin.
//   2D (plan, routing): one level, elements whose height reaches into it, inside the crop.
//   3D: the whole building, inside the crop: through the active 3D view when the user is in one (as Enscape renders it),
//       else the whole model at Fine detail (see ViewChoice).
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
                var view = Active3DView();
                var phase = DesignPhase(payload.RoomScan?.Phase);
                payload.ViewName = view?.Name ?? ViewChoice.WholeModelName;
                var meshes = new MeshReader(doc, view, e => InScope(e, phase));
                payload.Meshes = meshes.Read(area);
                payload.MeshScan = meshes.Scan;
            }
            else payload.KeepMeshes = true;
            return payload;
        }

        // ---- where the 3D comes from ----

        /// <summary>
        /// The active view when it is a parallel 3D view, else null (the whole model is read). A perspective camera view cannot be
        /// read the way a parallel one can (geometry and collectors by view), so it reads the whole model too; the header says which.
        /// </summary>
        View3D Active3DView()
        {
            var active = doc.ActiveView as View3D;
            var usable = active != null && !active.IsTemplate && !active.IsPerspective;
            return ViewChoice.Choose(usable) == ViewSource.Active ? active : null;
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

            var rooms = new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms)
                .WhereElementIsNotElementType().OfType<Room>().Where(InPrimaryOption).ToDictionary(r => r.UniqueId);
            var scan = RoomScope.Choose(rooms.Values.Select(r => Candidate(r, level)).ToList(), (doc.GetElement(phase) as Phase)?.Name);
            payload.RoomScan = scan;
            var options = new SpatialElementBoundaryOptions();
            foreach (var id in scan.Chosen)
                payload.Rooms.Add(ReadRoom(rooms[id], options));

            return payload;
        }

        RoomCandidate Candidate(Room room, Level level)
        {
            var box = room.get_BoundingBox(null);
            return new RoomCandidate
            {
                Id = room.UniqueId,
                OnLevel = room.LevelId == level.Id,
                InLevelBand = box != null && box.Max.Z > band.Low && box.Min.Z < band.High,
                Phase = (doc.GetElement(room.get_Parameter(BuiltInParameter.ROOM_PHASE)?.AsElementId() ?? ElementId.InvalidElementId) as Phase)?.Name,
                InCrop = InCrop(room),
            };
        }

        // ---- scope: phase, design option, crop ----

        /// <summary>The phase the level's rooms are in (where the design lives), else the active view's phase.</summary>
        ElementId DesignPhase(string roomPhase) =>
            doc.Phases.Cast<Phase>().FirstOrDefault(p => p.Name == roomPhase)?.Id ?? ActivePhase();

        ElementId ActivePhase()
        {
            var fromView = doc.ActiveView?.get_Parameter(BuiltInParameter.VIEW_PHASE)?.AsElementId();
            if (fromView != null && fromView != ElementId.InvalidElementId) return fromView;
            return doc.Phases.Size == 0 ? ElementId.InvalidElementId : doc.Phases.get_Item(doc.Phases.Size - 1).Id;
        }

        static bool InPrimaryOption(Element e) => e.DesignOption == null || e.DesignOption.IsPrimary;

        static bool InScope(Element e, ElementId phase)
        {
            if (!InPrimaryOption(e)) return false;
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

        /// <summary>
        /// The opening as a segment across its host wall, centred on the family instance. A door panel in a curtain (glass) wall
        /// has no insertion point and usually no door width, so its box centre and its panel width (or box size along the wall) stand in.
        /// </summary>
        static void AddOpening(List<List<double[]>> into, FamilyInstance fi, BuiltInParameter widthParameter)
        {
            var box = fi.get_BoundingBox(null);
            var at = (fi.Location as LocationPoint)?.Point ?? (box == null ? null : (box.Min + box.Max) / 2);
            if (at == null) return;
            var width = WidthOf(fi, widthParameter) ?? WidthOf(fi, BuiltInParameter.CURTAIN_WALL_PANELS_WIDTH) ?? 0;

            var along = box != null && box.Max.Y - box.Min.Y > box.Max.X - box.Min.X ? XYZ.BasisY : XYZ.BasisX;
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
            if (width <= 0 && box != null && fi.Location is not LocationPoint)
                width = Math.Abs((box.Max.X - box.Min.X) * along.X) + Math.Abs((box.Max.Y - box.Min.Y) * along.Y);
            if (width <= 0) width = DefaultOpeningWidthFt;
            var half = along * (width / 2);
            into.Add(new List<double[]> { Pt(at - half), Pt(at + half) });
        }

        static double? WidthOf(FamilyInstance fi, BuiltInParameter parameter)
        {
            var width = (fi.get_Parameter(parameter) ?? fi.Symbol?.get_Parameter(parameter))?.AsDouble() ?? 0;
            return width > 0 ? width : (double?)null;
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
