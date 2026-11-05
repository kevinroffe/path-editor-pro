/* Bridge between the page and whatever hosts it: the Revit add-in's WebView2 window (?host=revit) or a plain browser.
   The add-in starts the engine with a per-session key and opens the page as ?host=revit&key=...; the key rides on
   every API call as X-Qbiq-Key. Messages from the add-in arrive as {type, ...}; unknown types are ignored. */

function hostMode(search) {
  return new URLSearchParams(search).get('host') === 'revit' ? 'revit' : 'browser';
}

function engineKey(search) {
  return new URLSearchParams(search).get('key') || null;
}

function authHeaders(search) {
  const key = engineKey(search);
  return key ? { 'X-Qbiq-Key': key } : {};
}

/* Runs the handler named by msg.type; false for anything that is not a known handler (including inherited names). */
function handleHostMessage(msg, handlers) {
  if (!msg || typeof msg.type !== 'string' || !Object.prototype.hasOwnProperty.call(handlers || {}, msg.type)) return false;
  handlers[msg.type](msg);
  return true;
}

function postToHost(msg) {
  if (typeof window !== 'undefined' && window.chrome && window.chrome.webview) window.chrome.webview.postMessage(msg);
}

/* Adds the key to every engine call made with fetch; installed once, so call sites stay untouched. */
function installAuthFetch(search) {
  const headers = authHeaders(search);
  if (!Object.keys(headers).length) return;
  const original = window.fetch.bind(window);
  window.fetch = (url, init = {}) => original(url, { ...init, headers: { ...headers, ...(init.headers || {}) } });
}

if (typeof window !== 'undefined') {
  window.QbiqHost = { hostMode, engineKey, authHeaders, handleHostMessage, postToHost, handlers: {} };
  installAuthFetch(window.location.search);
  if (window.chrome && window.chrome.webview) {
    window.chrome.webview.addEventListener('message', e => handleHostMessage(e.data, window.QbiqHost.handlers));
  }
}

if (typeof module === 'object') {
  module.exports = { hostMode, engineKey, authHeaders, handleHostMessage, postToHost };
}
