// The path editor window: a WebView2 showing the engine's page (?host=revit). It asks the ExternalEvent to read the
// model, POSTs the payload straight to the engine (so no big JSON crosses the page bridge), then tells the page to load it.
// The page's "Save path (XML)" download is caught here so the user picks where the file goes.
// The window opens at once: the engine starts in the background and a "starting" note shows until it answers.
using System;
using System.IO;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Interop;
using Autodesk.Revit.UI;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.Wpf;
using Newtonsoft.Json.Linq;
using Qbiq.PathTool.Core;

namespace Qbiq.PathTool.Addin
{
    public sealed class PathToolWindow : Window
    {
        readonly Task<EngineEndpoint> engine;
        readonly ExternalEvent readEvent;
        readonly ReadModelEvent handler;
        readonly WebView2 web = new WebView2();
        readonly TextBlock status = new TextBlock
        {
            Text = "Starting the path engine…", FontSize = 16, Foreground = System.Windows.Media.Brushes.Gray,
            HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center,
        };
        EngineEndpoint endpoint;
        bool firstLoadRequested;

        public PathToolWindow(IntPtr revitWindow, Task<EngineEndpoint> engine, ExternalEvent readEvent, ReadModelEvent handler)
        {
            this.engine = engine;
            this.readEvent = readEvent;
            this.handler = handler;
            Title = "Path Tool";
            Width = 1400;
            Height = 860;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;
            var grid = new Grid();
            grid.Children.Add(web);
            grid.Children.Add(status);
            Content = grid;
            new WindowInteropHelper(this) { Owner = revitWindow };   // floats above Revit, closes with it
            handler.Done = OnModelRead;
            Loaded += async (s, e) => await InitAsync();
        }

        async Task InitAsync()
        {
            try
            {
                endpoint = await engine;                              // the engine starts in the background
                var data = Path.Combine(Session.StateDir, "webview");
                var env = await CoreWebView2Environment.CreateAsync(null, data);
                await web.EnsureCoreWebView2Async(env);
            }
            catch (EngineStartException e)
            {
                TaskDialog.Show("Qbiq Path Tool", e.Message);
                Close();
                return;
            }
            catch (Exception e)
            {
                TaskDialog.Show("Qbiq Path Tool", "The path editor window could not start. It needs the Microsoft Edge WebView2 Runtime " +
                    "(installed with current Windows and Edge).\n\n" + e.Message);
                Close();
                return;
            }
            web.CoreWebView2.WebMessageReceived += (s, e) =>
            {
                if (MessageType(e.WebMessageAsJson) == "refreshModel") RequestRead(true);
            };
            web.CoreWebView2.DownloadStarting += OnDownload;
            web.CoreWebView2.NavigationCompleted += (s, e) =>
            {
                if (!e.IsSuccess) return;
                status.Visibility = Visibility.Collapsed;
                if (!firstLoadRequested) { firstLoadRequested = true; RequestRead(false); }
            };
            web.Source = new Uri(endpoint.BaseUri, "?host=revit&key=" + endpoint.Key);
        }

        static string MessageType(string json)
        {
            try { return (string)JObject.Parse(json)["type"]; }
            catch (Exception) { return null; }
        }

        void Post(string json)
        {
            if (web.CoreWebView2 != null) web.CoreWebView2.PostWebMessageAsJson(json);
        }

        void RequestRead(bool refresh)
        {
            handler.Refresh = refresh;
            Post("{\"type\":\"modelReading\"}");                      // the page shows "Reading the Revit model…"
            readEvent.Raise();
        }

        void OnDownload(object sender, CoreWebView2DownloadStartingEventArgs e)
        {
            var dialog = new Microsoft.Win32.SaveFileDialog { FileName = "enscape_walkpath.xml", DefaultExt = ".xml", Filter = "Enscape path (*.xml)|*.xml" };
            if (dialog.ShowDialog(this) == true) { e.ResultFilePath = dialog.FileName; e.Handled = true; }
            else e.Cancel = true;
        }

        /// <summary>On Revit's thread: the model is read. Serialising and sending happen off-thread; then the page is told.</summary>
        void OnModelRead(LevelPayload payload, bool refresh, string error)
        {
            if (Session.Window != this || web.CoreWebView2 == null) return;           // the window was closed meanwhile
            if (payload == null)
            {
                Post("{\"type\":\"modelFailed\"}");
                TaskDialog.Show("Qbiq Path Tool", error ?? "The model could not be read.");
                return;
            }
            Task.Run(async () =>
            {
                try
                {
                    var json = PayloadJson.Serialize(payload);
                    using (var http = new HttpClient { Timeout = TimeSpan.FromMinutes(5) })
                    using (var request = new HttpRequestMessage(HttpMethod.Post, new Uri(endpoint.BaseUri, "api/upload-revit")))
                    {
                        request.Headers.Add("X-Qbiq-Key", endpoint.Key);
                        request.Content = new StringContent(json, Encoding.UTF8, "application/json");
                        var response = await http.SendAsync(request).ConfigureAwait(false);
                        var body = await response.Content.ReadAsStringAsync().ConfigureAwait(false);
                        if (!response.IsSuccessStatusCode) throw new InvalidOperationException(ErrorText(body));
                    }
                    await Dispatcher.InvokeAsync(() =>
                    {
                        if (Session.Window == this) Post(refresh ? "{\"type\":\"modelRefreshed\"}" : "{\"type\":\"modelLoaded\"}");
                    });
                }
                catch (Exception e)
                {
                    await Dispatcher.InvokeAsync(() =>
                    {
                        if (Session.Window != this) return;
                        Post("{\"type\":\"modelFailed\"}");
                        TaskDialog.Show("Qbiq Path Tool", "The engine could not load the model: " + e.Message);
                    });
                }
            });
        }

        /// <summary>The engine answers errors as {"error": "..."}; anything else is shown as it is.</summary>
        static string ErrorText(string body)
        {
            try { return (string)JObject.Parse(body)["error"] ?? body; }
            catch (Exception) { return body; }
        }

        protected override void OnClosed(EventArgs e)
        {
            Session.Window = null;
            web.Dispose();
            base.OnClosed(e);
        }
    }
}
