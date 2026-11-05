using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Qbiq.PathTool.Core;
using Xunit;

namespace Qbiq.PathTool.Tests
{
    public class LevelBandTests
    {
        [Fact]
        public void A_level_reads_from_just_above_its_floor_to_just_below_the_next_level()
        {
            var band = LevelBand.For(10, new[] { 0.0, 10, 20 });
            Assert.Equal(10.1, band.Low, 9);
            Assert.Equal(19.9, band.High, 9);
        }

        [Fact]
        public void The_top_level_gets_a_default_storey_height()
        {
            var band = LevelBand.For(20, new[] { 20.0, 0, 10 });                 // order does not matter
            Assert.Equal(20.1, band.Low, 9);
            Assert.Equal(20 + LevelBand.DefaultStoreyFt - 0.1, band.High, 9);
        }

        [Fact]
        public void A_wall_spanning_several_levels_is_inside_every_levels_band()
        {
            var wallBottom = 0.0; var wallTop = 50.0;
            foreach (var elevation in new[] { 0.0, 10, 20, 30 })
            {
                var band = LevelBand.For(elevation, new[] { 0.0, 10, 20, 30 });
                Assert.True(wallBottom <= band.High && wallTop >= band.Low);
            }
        }
    }

    public class MeshBudgetTests
    {
        [Fact] public void The_shell_is_kept_past_the_budget() => Assert.True(MeshBudget.Allows("wall", 2_900_000, 1_000_000));
        [Fact] public void Floors_ceilings_and_roofs_are_shell_too() => Assert.All(new[] { "floor", "ceiling", "roof" }, t => Assert.True(MeshBudget.Allows(t, 2_900_000, 1_000_000)));
        [Fact] public void Even_the_shell_stops_at_three_times_the_budget() => Assert.All(new[] { "wall", "floor", "ceiling", "roof" }, t => Assert.False(MeshBudget.Allows(t, 3_000_000, 1_000_000)));
        [Fact] public void Detail_is_kept_while_under_budget() => Assert.True(MeshBudget.Allows("furniture", 10, 1_000_000));
        [Fact] public void Detail_stops_once_over_budget() => Assert.False(MeshBudget.Allows("furniture", 1_000_000, 1_000_000));
    }

    public class IndexedMeshTests
    {
        static readonly double[][] Quad = { new double[] { 0, 0, 0 }, new double[] { 1, 0, 0 }, new double[] { 1, 1, 0 }, new double[] { 0, 1, 0 } };

        [Fact]
        public void A_face_keeps_its_shared_vertices()
        {
            var b = new MeshBuilder();
            b.AddIndexed("wall", "#ffffff", null, Quad, new[] { 0, 1, 2, 0, 2, 3 });
            var m = Assert.Single(b.Build());
            Assert.Equal(12, m.Verts.Count);                    // 4 vertices, not 6
            Assert.Equal(new[] { 0, 1, 2, 0, 2, 3 }, m.Faces);
            Assert.Equal(4, b.VertexCount);
        }

        [Fact]
        public void A_second_face_in_the_same_material_is_offset()
        {
            var b = new MeshBuilder();
            b.AddIndexed("wall", "#ffffff", null, Quad, new[] { 0, 1, 2, 0, 2, 3 });
            b.AddIndexed("wall", "#ffffff", null, Quad, new[] { 0, 1, 2 });
            var m = Assert.Single(b.Build());
            Assert.Equal(new[] { 0, 1, 2, 0, 2, 3, 4, 5, 6 }, m.Faces);
        }
    }

    public class EngineAliveTests : IDisposable
    {
        static readonly string Python = Environment.GetEnvironmentVariable("QBIQ_TEST_PYTHON") ?? "python";
        static readonly string Fake = Path.Combine(AppContext.BaseDirectory, "fake_engine.py");
        readonly string stateDir = Path.Combine(Path.GetTempPath(), "qbiq-alive-" + Guid.NewGuid().ToString("N"));
        EngineHost host;

        public void Dispose()
        {
            host?.Stop();
            try { Directory.Delete(stateDir, true); } catch { }
        }

        [Fact]
        public async Task A_dead_engine_is_noticed()
        {
            host = new EngineHost(Python, stateDir, new[] { Fake });
            Assert.False(host.IsAlive);                                   // not started yet
            await host.StartAsync();
            Assert.True(host.IsAlive);
            using (var p = Process.GetProcessById(host.ProcessId)) { p.Kill(); p.WaitForExit(5000); }
            Assert.False(host.IsAlive);
        }

        [Fact]
        public async Task A_stopped_host_is_not_alive()
        {
            host = new EngineHost(Python, stateDir, new[] { Fake });
            await host.StartAsync();
            host.Stop();
            Assert.False(host.IsAlive);
        }
    }
}
