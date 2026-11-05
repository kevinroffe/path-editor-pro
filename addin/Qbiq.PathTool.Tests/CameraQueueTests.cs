using System.Linq;
using Qbiq.PathTool.Core;
using Xunit;

namespace Qbiq.PathTool.Tests
{
    public class CameraQueueTests
    {
        static CameraMessage Pose(double x) => new CameraMessage { Type = "camera", X = x };
        static CameraMessage Of(string type) => new CameraMessage { Type = type };

        [Fact]
        public void Poses_that_pile_up_become_the_latest_one()
        {
            var q = new CameraQueue();
            q.Enqueue(Pose(1)); q.Enqueue(Pose(2)); q.Enqueue(Pose(3));
            var all = q.Drain();
            Assert.Single(all);
            Assert.Equal(3, all[0].X);
        }

        [Fact]
        public void Stop_then_start_both_survive_in_order_so_the_view_is_restored_before_it_is_saved_again()
        {
            var q = new CameraQueue();
            q.Enqueue(Of("cameraStop")); q.Enqueue(Of("cameraStart"));
            Assert.Equal(new[] { "cameraStop", "cameraStart" }, q.Drain().Select(m => m.Type).ToArray());
        }

        [Fact]
        public void Start_then_poses_keeps_the_start_and_only_the_latest_pose()
        {
            var q = new CameraQueue();
            q.Enqueue(Of("cameraStart")); q.Enqueue(Pose(1)); q.Enqueue(Pose(2));
            var all = q.Drain();
            Assert.Equal(new[] { "cameraStart", "camera" }, all.Select(m => m.Type).ToArray());
            Assert.Equal(2, all[1].X);
        }

        [Fact]
        public void Draining_empties_the_queue()
        {
            var q = new CameraQueue();
            q.Enqueue(Pose(1));
            q.Drain();
            Assert.Empty(q.Drain());
        }
    }
}
