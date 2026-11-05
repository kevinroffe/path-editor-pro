// The path editor window: a WebView2 showing the engine's page (?host=revit). It asks the ExternalEvent to read the
// model, POSTs the payload straight to the engine (so no big JSON crosses the page bridge), then tells the page to load it.
// The page's "Save path (XML)" download is caught here so the user picks where the file goes.
using System;
using System.IO;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Interop;
using Autodesk.Revit.UI;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.Wpf;
using Qbiq.PathTool.Core;

namespace Qbiq.PathTool.Addin
{
    public sealed class PathToolWindow : Window
    {
        readonly EngineEndpoint endpoint;
        readonly ExternalEvent readEvent;
        readonly ReadModelEvent handler;
        readonly WebView2 web = new WebView2();
        bool firstLoadRequested;

        public PathToolWindow(IntPtr revitWindow, EngineEndpoint endpoint, ExternalEvent readEvent, ReadModelEvent handler)
        {
            this.endpoint = endpoint;
            this.readEvent = readEvent;
            this.handler = handler;
            Title = "Path Tool";
            Width = 1400;
            Height = 860;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;
            Content = web;
            new WindowInteropHelper(this) { Owner = revitWindow };   // floats above Revit, closes with it
            handler.Done = OnModelRead;
            Loaded += async (s, e) => await InitAsync();
        }

        async Task InitAsync()
        {
            try
            {
                var data = Path.Combine(Session.StateDir, "webview");
                var env = await CoreWebView2Environment.CreateAsync(null, data);
                await web.EnsureCoreWebView2Async(env);
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
                if (e.WebMessageAsJson.Contains("\"refreshModel\"")) RequestRead(true);
            };
            web.CoreWebView2.DownloadStarting += OnDownload;
            web.CoreWebView2.NavigationCompleted += (s, e) =>
            {
                if (!firstLoadRequested && e.IsSuccess) { firstLoadRequested = true; RequestRead(false); }
            };
            web.Source = new Uri(endpoint.BaseUri, "?host=revit&key=" + endpoint.Key);
        }

        void RequestRead(bool refresh)
        {
            handler.Refresh = refresh;
            readEvent.Raise();
        }

        void OnDownload(object sender, CoreWebView2DownloadStartingEventArgs e)
        {
            var dialog = new Microsoft.Win32.SaveFileDialog { FileName = "enscape_walkpath.xml", DefaultExt = ".xml", Filter = "Enscape path (*.xml)|*.xml" };
            if (dialog.ShowDialog(this) == true) { e.ResultFilePath = dialog.FileName; e.Handled = true; }
            else e.Cancel = true;
        }

        /// <summary>On Revit's thread: the model is read; send it to the engine off-thread, then tell the page.</summary>
        void OnModelRead(string json, bool refresh, string error)
        {
            if (json == null) { TaskDialog.Show("Qbiq Path Tool", error ?? "The model could not be read."); return; }
            Task.Run(async () =>
            {
                try
                {
                    using (var http = new HttpClient { Timeout = TimeSpan.FromMinutes(5) })
                    using (var request = new HttpRequestMessage(HttpMethod.Post, new Uri(endpoint.BaseUri, "api/upload-revit")))
                    {
                        request.Headers.Add("X-Qbiq-Key", endpoint.Key);
                        request.Content = new StringContent(json, Encoding.UTF8, "application/json");
                        var response = await http.SendAsync(request).ConfigureAwait(false);
                        if (!response.IsSuccessStatusCode)
                            throw new InvalidOperationException(await response.Content.ReadAsStringAsync().ConfigureAwait(false));
                    }
                    await Dispatcher.InvokeAsync(() =>
                        web.CoreWebView2.PostWebMessageAsJson(refresh ? "{\"type\":\"modelRefreshed\"}" : "{\"type\":\"modelLoaded\"}"));
                }
                catch (Exception e)
                {
                    await Dispatcher.InvokeAsync(() => TaskDialog.Show("Qbiq Path Tool", "The engine could not load the model: " + e.Message));
                }
            });
        }

        protected override void OnClosed(EventArgs e)
        {
            Session.Window = null;
            web.Dispose();
            base.OnClosed(e);
        }
    }
}
