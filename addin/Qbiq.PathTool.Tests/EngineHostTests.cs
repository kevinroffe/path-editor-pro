using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Sockets;
using System.Threading.Tasks;
using Qbiq.PathTool.Core;
using Xunit;

namespace Qbiq.PathTool.Tests
{
    public class EngineHostTests : IDisposable
    {
        static readonly string Python = Environment.GetEnvironmentVariable("QBIQ_TEST_PYTHON") ?? "python";
        static readonly string Fake = Path.Combine(AppContext.BaseDirectory, "fake_engine.py");
        readonly string stateDir = Path.Combine(Path.GetTempPath(), "qbiq-enginehost-" + Guid.NewGuid().ToString("N"));
        readonly System.Collections.Generic.List<EngineHost> hosts = new System.Collections.Generic.List<EngineHost>();

        public EngineHostTests() { Directory.CreateDirectory(stateDir); }

        public void Dispose()
        {
            foreach (var h in hosts) h.Stop();
            try { Directory.Delete(stateDir, true); } catch { }
        }

        EngineHost NewHost()
        {
            var h = new EngineHost(Python, stateDir, new[] { Fake });
            hosts.Add(h);
            return h;
        }

        static async Task<HttpStatusCode> Ping(EngineEndpoint ep, string key)
        {
            using (var http = new HttpClient())
            using (var req = new HttpRequestMessage(HttpMethod.Get, new Uri(ep.BaseUri, "api/ping")))
            {
                if (key != null) req.Headers.Add("X-Qbiq-Key", key);
                return (await http.SendAsync(req)).StatusCode;
            }
        }

        [Fact]
        public async Task Start_returns_reachable_endpoint_with_key()
        {
            var ep = await NewHost().StartAsync();
            Assert.Equal("127.0.0.1", ep.BaseUri.Host);
            Assert.Equal(HttpStatusCode.OK, await Ping(ep, ep.Key));
        }

        [Fact]
        public async Task Key_is_random_per_start_and_reaches_the_engine()
        {
            var a = await NewHost().StartAsync();
            var b = await NewHost().StartAsync();
            Assert.Equal(64, a.Key.Length);
            Assert.NotEqual(a.Key, b.Key);
            Assert.Equal(HttpStatusCode.OK, await Ping(a, a.Key));
            Assert.Equal(HttpStatusCode.Forbidden, await Ping(a, b.Key));
            Assert.Equal(HttpStatusCode.Forbidden, await Ping(a, null));
        }

        [Fact]
        public async Task Stop_kills_the_process()
        {
            var host = NewHost();
            var ep = await host.StartAsync();
            var pid = host.ProcessId;
            host.Stop();
            await Assert.ThrowsAnyAsync<HttpRequestException>(() => Ping(ep, ep.Key));
            Assert.False(EngineHost.IsRunning(pid));
        }

        [Fact]
        public async Task Two_starts_use_different_ports()
        {
            var a = await NewHost().StartAsync();
            var b = await NewHost().StartAsync();
            Assert.NotEqual(a.Port, b.Port);
        }

        [Fact]
        public void A_busy_port_is_never_chosen()
        {
            var held = new TcpListener(IPAddress.Loopback, 0);
            held.Start();
            try
            {
                var busy = ((IPEndPoint)held.LocalEndpoint).Port;
                for (var i = 0; i < 50; i++) Assert.NotEqual(busy, EngineHost.FindFreePort());
            }
            finally { held.Stop(); }
        }

        [Fact]
        public void Start_fails_with_a_clear_message_if_the_engine_is_missing()
        {
            var host = new EngineHost(Path.Combine(stateDir, "nope.exe"), stateDir);
            var ex = Assert.ThrowsAsync<EngineStartException>(() => host.StartAsync()).Result;
            Assert.Contains("nope.exe", ex.Message);
        }

        static Process Spawn()
        {
            return Process.Start(new ProcessStartInfo(Python, "\"" + Fake + "\" --port " + EngineHost.FindFreePort())
                { UseShellExecute = false, CreateNoWindow = true });
        }

        [Fact]
        public void ReapOrphans_kills_a_stale_engine_from_the_pid_file()
        {
            var engine = Spawn();
            var dead = Process.Start(new ProcessStartInfo(Python, "-c pass") { UseShellExecute = false, CreateNoWindow = true });
            dead.WaitForExit();
            var pidFile = Path.Combine(stateDir, "engine-" + dead.Id + ".pid");
            File.WriteAllText(pidFile, engine.Id + ":" + dead.Id + ":" + engine.StartTime.ToUniversalTime().Ticks);
            Assert.Equal(1, EngineHost.ReapOrphans(stateDir));
            engine.WaitForExit(5000);
            Assert.False(EngineHost.IsRunning(engine.Id));
            Assert.False(File.Exists(pidFile));
        }

        [Fact]
        public void ReapOrphans_leaves_an_engine_whose_revit_is_still_running()
        {
            var engine = Spawn();
            try
            {
                File.WriteAllText(Path.Combine(stateDir, "engine-" + Process.GetCurrentProcess().Id + ".pid"),
                    engine.Id + ":" + Process.GetCurrentProcess().Id + ":" + engine.StartTime.ToUniversalTime().Ticks);
                Assert.Equal(0, EngineHost.ReapOrphans(stateDir));
                Assert.True(EngineHost.IsRunning(engine.Id));
            }
            finally { try { engine.Kill(); } catch { } }
        }
    }
}
