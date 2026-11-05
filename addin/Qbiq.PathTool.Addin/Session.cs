// State shared by the ribbon commands for the lifetime of the Revit session: the one engine process and the window.
using System;
using System.IO;
using System.Reflection;
using System.Threading.Tasks;
using Qbiq.PathTool.Core;

namespace Qbiq.PathTool.Addin
{
    internal static class Session
    {
        public static readonly string StateDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Qbiq", "PathTool");

        static EngineHost host;
        public static PathToolWindow Window;

        static string AddinDir => Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);

        /// <summary>The packaged engine next to the add-in; for development, QBIQ_ENGINE_PYTHON + QBIQ_ENGINE_SCRIPT (run.py) override it.</summary>
        static EngineHost CreateHost()
        {
            var packaged = Path.Combine(AddinDir, "engine", "qbiq-engine.exe");
            var python = Environment.GetEnvironmentVariable("QBIQ_ENGINE_PYTHON");
            var script = Environment.GetEnvironmentVariable("QBIQ_ENGINE_SCRIPT");
            if (!File.Exists(packaged) && !string.IsNullOrEmpty(python) && !string.IsNullOrEmpty(script))
                return new EngineHost(python, StateDir, new[] { "-X", "utf8", script });
            return new EngineHost(packaged, StateDir);
        }

        static Task<EngineEndpoint> starting;

        /// <summary>
        /// The engine, started on first use and restarted if it has died (antivirus, a crash). Returns at once with a task so
        /// Revit's UI is never blocked while the engine comes up; the window shows "starting" until it completes.
        /// </summary>
        public static Task<EngineEndpoint> EnsureEngineAsync()
        {
            if (starting != null && host != null && host.IsAlive) return starting;
            host?.Stop();
            EngineHost.ReapOrphans(StateDir);
            host = CreateHost();
            var thisHost = host;
            starting = Task.Run(() => thisHost.StartAsync());
            return starting;
        }

        public static void Shutdown()
        {
            host?.Stop();
            host = null;
            starting = null;
        }
    }
}
