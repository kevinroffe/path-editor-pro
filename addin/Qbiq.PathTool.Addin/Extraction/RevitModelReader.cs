// Reads one level of the open Revit model as the contract payload (see Qbiq.PathTool.Core/Payload.cs).
// Read-only: no Transaction is ever opened. Coordinates are Revit's internal units (feet) and internal origin.
// Version-one scope: the active view's phase, the primary design option, linked models are ignored.
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

        // Mesh types are the names the 3D view colours by. Roofs are left out in version one: from above they hide the plan.
        static readonly (BuiltInCategory, string)[] MeshCategories =
        {
            (BuiltInCategory.OST_Walls, "wall"), (BuiltInCategory.OST_Floors, "floor"), (BuiltInCategory.OST_Ceilings, "ceiling"),
            (BuiltInCategory.OST_Doors, "door"), (BuiltInCategory.OST_Windows, "window"),
            (BuiltInCategory.OST_Columns, "column"), (BuiltInCategory.OST_StructuralColumns, "column"),
            (BuiltInCategory.OST_StructuralFraming, "beam"), (BuiltInCategory.OST_Stairs, "stair"),
            (BuiltInCategory.OST_Furniture, "furniture"), (BuiltInCategory.OST_FurnitureSystems, "furniture"),
            (BuiltInCategory.OST_Casework, "furniture"), (BuiltInCategory.OST_LightingFixtures, "light"),
            (BuiltInCategory.OST_GenericModel, "other"), (BuiltInCategory.OST_Railings, "other"),
        };

        readonly Document doc;
        LevelBand band;                       // the height band of the level being read (see OnLevel)

        public RevitModelReader(Document doc) { this.doc = doc; }

        public IReadOnlyList<string> LevelNames() =>
            new FilteredElementCollector(doc).OfClass(typeof(Level)).Cast<Level>()
                .OrderBy(l => l.Elevation).Select(l => l.Name).ToList();

        public LevelPayload ReadLevel(string levelName)
        {
            var level = new FilteredElementCollector(doc).OfClass(typeof(Level)).Cast<Level>()
                .FirstOrDefault(l => l.Name == levelName);
            if (level == null)
                throw new ArgumentException("No level '" + levelName + "' in this model; available: " + string.Join(", ", LevelNames()));

            var phase = ActivePhase();
            band = LevelBand.For(level.Elevation,
                new FilteredElementCollector(doc).OfClass(typeof(Level)).Cast<Level>().Select(l => l.Elevation).ToList());
            var payload = new LevelPayload
            {
                Level = new LevelInfo { Name = level.Name, Elevation = level.Elevation },
                UnitsToMetres = FeetToMetres,
            };

            foreach (var wall in OnLevel(BuiltInCategory.OST_Walls, level, phase).OfType<Wall>())
            {
                var curve = (wall.Location as LocationCurve)?.Curve;
                if (curve != null) payload.Walls.Add(Polyline(curve.Tessellate()));
            }
            foreach (var door in OnLevel(BuiltInCategory.OST_Doors, level, phase).OfType<FamilyInstance>())
                AddOpening(payload.Doors, door, BuiltInParameter.DOOR_WIDTH);
            foreach (var window in OnLevel(BuiltInCategory.OST_Windows, level, phase).OfType<FamilyInstance>())
                AddOpening(payload.Windows, window, BuiltInParameter.WINDOW_WIDTH);
            foreach (var cat in new[] { BuiltInCategory.OST_Columns, BuiltInCategory.OST_StructuralColumns })
                foreach (var column in OnLevel(cat, level, phase)) AddBox(payload.Columns, column);
            foreach (var cat in new[] { BuiltInCategory.OST_Furniture, BuiltInCategory.OST_FurnitureSystems, BuiltInCategory.OST_Casework })
                foreach (var item in OnLevel(cat, level, phase)) AddBox(payload.Furniture, item);

            var options = new SpatialElementBoundaryOptions();
            foreach (var room in new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms)
                         .WhereElementIsNotElementType().OfType<Room>().Where(r => r.LevelId == level.Id && InScope(r, phase)))
                payload.Rooms.Add(ReadRoom(room, options));

            var meshes = new MeshReader(doc);
            foreach (var (category, type) in MeshCategories)
                foreach (var element in OnLevel(category, level, phase)) meshes.AddElement(element, type);
            payload.Meshes = meshes.Build();

            return payload;
        }

        // ---- scope: phase and design option ----

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

        /// <summary>
        /// Floors and ceilings belong to the level they are built on. Everything else belongs to every level its height
        /// reaches into: a facade or core wall whose base is Level 1 and top is Level 5 must appear when Level 3 is read.
        /// </summary>
        IEnumerable<Element> OnLevel(BuiltInCategory category, Level level, ElementId phase)
        {
            var collector = new FilteredElementCollector(doc).OfCategory(category).WhereElementIsNotElementType();
            if (category == BuiltInCategory.OST_Floors || category == BuiltInCategory.OST_Ceilings)
                collector = collector.WherePasses(new ElementLevelFilter(level.Id));
            else
                collector = collector.WherePasses(new BoundingBoxIntersectsFilter(
                    new Outline(new XYZ(-1e7, -1e7, band.Low), new XYZ(1e7, 1e7, band.High))));
            return collector.Where(e => InScope(e, phase));
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
