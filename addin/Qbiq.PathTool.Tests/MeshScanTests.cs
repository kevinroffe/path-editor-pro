using Qbiq.PathTool.Core;
using Xunit;

namespace Qbiq.PathTool.Tests
{
    public class MeshScanTests
    {
        [Fact]
        public void Counts_each_outcome_per_type()
        {
            var scan = new MeshScan();
            scan.Count("furniture", MeshOutcome.Read);
            scan.Count("furniture", MeshOutcome.ReadAtFine);
            scan.Count("furniture", MeshOutcome.Empty);
            scan.Count("wall", MeshOutcome.Failed);
            Assert.Equal(new[] { 3, 2, 1, 1, 0 }, scan.Types["furniture"].ToArray());   // read at Fine still counts as read
            Assert.Equal(new[] { 1, 0, 0, 0, 1 }, scan.Types["wall"].ToArray());
        }

        [Fact]
        public void Summary_names_the_types_with_missing_geometry()
        {
            var scan = new MeshScan();
            scan.Count("furniture", MeshOutcome.Read);
            scan.Count("furniture", MeshOutcome.Empty);
            scan.Count("wall", MeshOutcome.Read);
            Assert.Equal("3D: furniture 1/2 (1 empty), wall 1/1", scan.Summary());
        }
    }
}
