// Camera messages wait here for Revit's main thread. Raise() calls pile up, so the order matters: a stop followed by a start must
// both run (restore the view, then save it again), while poses that pile up only need the latest one.
using System.Collections.Generic;

namespace Qbiq.PathTool.Core
{
    public sealed class CameraQueue
    {
        readonly object gate = new object();
        readonly List<CameraMessage> items = new List<CameraMessage>();

        public void Enqueue(CameraMessage message)
        {
            lock (gate)
            {
                var last = items.Count - 1;
                if (message.Type == "camera" && last >= 0 && items[last].Type == "camera") items[last] = message;
                else items.Add(message);
            }
        }

        /// <summary>Everything waiting, oldest first; the queue is empty afterwards.</summary>
        public List<CameraMessage> Drain()
        {
            lock (gate)
            {
                var all = new List<CameraMessage>(items);
                items.Clear();
                return all;
            }
        }
    }
}
