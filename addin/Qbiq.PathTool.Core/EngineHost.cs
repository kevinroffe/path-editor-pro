// Starts and stops the local engine (the packaged backend). It listens on 127.0.0.1 only, on a free port, and only
// answers API calls that carry this session's random key. A pid file per Revit process lets the next Revit session
// clean up an engine left behind by a crash.
using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;

namespace Qbiq.PathTool.Core
{
    public sealed class EngineEndpoint
    {
        public int Port { get; set; }
        public string Key { get; set; }
        public Uri BaseUri => new Uri("http://127.0.0.1:" + Port + "/");
    }

    public class EngineStartException : Exception
    {
        public EngineStartException(string message) : base(message) { }
        public EngineStartException(string message, Exception inner) : base(message, inner) { }
    }

    public sealed class EngineHost : IDisposable
    {
        readonly string enginePath;
        readonly string stateDir;
        readonly string[] baseArgs;
        Process process;
        string pidFile;

        public TimeSpan StartTimeout { get; set; } = TimeSpan.FromSeconds(30);
        public int ProcessId => process == null ? 0 : process.Id;

        /// <param name="baseArgs">Arguments placed before --port/--key (a script path when the engine is an interpreter).</param>
        public EngineHost(string enginePath, string stateDir, string[] baseArgs = null)
        {
            this.enginePath = enginePath;
            this.stateDir = stateDir;
            this.baseArgs = baseArgs ?? new string[0];
        }

        public async Task<EngineEndpoint> StartAsync()
        {
            if (Path.IsPathRooted(enginePath) && !File.Exists(enginePath))
                throw new EngineStartException("The path-tool engine was not found at " + enginePath + ". Reinstall the add-in.");
            Directory.CreateDirectory(stateDir);

            var endpoint = new EngineEndpoint { Port = FindFreePort(), Key = RandomKey() };
            var args = string.Join(" ", baseArgs.Select(a => "\"" + a + "\"")
                .Concat(new[] { "--port", endpoint.Port.ToString(), "--key", endpoint.Key }));
            var info = new ProcessStartInfo(enginePath, args) { UseShellExecute = false, CreateNoWindow = true };
            info.EnvironmentVariables["QBIQ_ENGINE_KEY"] = endpoint.Key;
            info.EnvironmentVariables["PYTHONUTF8"] = "1";
            try { process = Process.Start(info); }
            catch (Exception e) { throw new EngineStartException("Could not start the engine '" + enginePath + "': " + e.Message, e); }

            var parent = Process.GetCurrentProcess().Id;
            pidFile = Path.Combine(stateDir, "engine-" + parent + ".pid");
            File.WriteAllText(pidFile, process.Id + ":" + parent + ":" + process.StartTime.ToUniversalTime().Ticks);

            await WaitUntilReady(endpoint).ConfigureAwait(false);
            return endpoint;
        }

        async Task WaitUntilReady(EngineEndpoint endpoint)
        {
            var deadline = DateTime.UtcNow + StartTimeout;
            using (var http = new HttpClient { Timeout = TimeSpan.FromSeconds(2) })
            {
                while (DateTime.UtcNow < deadline)
                {
                    if (process.HasExited)
                    {
                        var code = process.ExitCode;
                        Stop();
                        throw new EngineStartException("The engine stopped right after starting (exit code " + code + ").");
                    }
                    try
                    {
                        if ((await http.GetAsync(endpoint.BaseUri).ConfigureAwait(false)).StatusCode == HttpStatusCode.OK) return;
                    }
                    catch (HttpRequestException) { }
                    catch (TaskCanceledException) { }
                    await Task.Delay(150).ConfigureAwait(false);
                }
            }
            Stop();
            throw new EngineStartException("The engine did not answer within " + (int)StartTimeout.TotalSeconds + " seconds.");
        }

        public void Stop()
        {
            if (process != null)
            {
                KillTree(process.Id);
                try { process.WaitForExit(5000); } catch { }
                process.Dispose();
                process = null;
            }
            if (pidFile != null)
            {
                try { File.Delete(pidFile); } catch { }
                pidFile = null;
            }
        }

        public void Dispose() => Stop();

        /// <summary>A port nothing is listening on right now.</summary>
        public static int FindFreePort()
        {
            var listener = new TcpListener(IPAddress.Loopback, 0);
            listener.Start();
            try { return ((IPEndPoint)listener.LocalEndpoint).Port; }
            finally { listener.Stop(); }
        }

        public static bool IsRunning(int pid)
        {
            try { using (var p = Process.GetProcessById(pid)) return !p.HasExited; }
            catch (ArgumentException) { return false; }
            catch (InvalidOperationException) { return false; }
        }

        /// <summary>Kills engines left by Revit sessions that no longer exist; returns how many were killed.</summary>
        public static int ReapOrphans(string stateDir)
        {
            if (!Directory.Exists(stateDir)) return 0;
            var reaped = 0;
            foreach (var file in Directory.GetFiles(stateDir, "engine-*.pid"))
            {
                var parts = SafeRead(file).Split(':');
                if (parts.Length != 3 || !int.TryParse(parts[0], out var enginePid) || !int.TryParse(parts[1], out var parentPid)
                    || !long.TryParse(parts[2], out var startTicks))
                {
                    TryDelete(file);
                    continue;
                }
                if (IsRunning(parentPid)) continue;                       // that Revit is still open: its engine is in use
                if (IsRunning(enginePid) && StartedAt(enginePid, startTicks)) { KillTree(enginePid); reaped++; }
                TryDelete(file);
            }
            return reaped;
        }

        static bool StartedAt(int pid, long ticks)
        {
            try { using (var p = Process.GetProcessById(pid)) return p.StartTime.ToUniversalTime().Ticks == ticks; }
            catch { return false; }
        }

        static void KillTree(int pid)
        {
            try
            {
                var kill = Process.Start(new ProcessStartInfo("taskkill", "/PID " + pid + " /T /F") { UseShellExecute = false, CreateNoWindow = true });
                kill.WaitForExit(5000);
            }
            catch
            {
                try { using (var p = Process.GetProcessById(pid)) p.Kill(); } catch { }
            }
        }

        static string SafeRead(string file) { try { return File.ReadAllText(file); } catch { return ""; } }
        static void TryDelete(string file) { try { File.Delete(file); } catch { } }

        static string RandomKey()
        {
            var bytes = new byte[32];
            using (var rng = RandomNumberGenerator.Create()) rng.GetBytes(bytes);
            var sb = new StringBuilder();
            foreach (var b in bytes) sb.Append(b.ToString("x2"));
            return sb.ToString();
        }
    }
}
