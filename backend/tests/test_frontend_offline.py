"""The Revit window runs with no network: index.html must not load anything from the internet."""
import re
from pathlib import Path

INDEX = Path(__file__).resolve().parents[2] / "frontend" / "index.html"


def test_index_has_no_external_urls():
    html = INDEX.read_text(encoding="utf-8")
    refs = re.findall(r"""<(?:script|link)\b[^>]*\b(?:src|href)=["'](https?://[^"']+)""", html)
    refs += re.findall(r"""@import\s+url\(\s*['"]?(https?://[^'")\s]+)""", html)
    refs += re.findall(r'"[^"\n]+"\s*:\s*"(https?://[^"]+)"', html[html.find('type="importmap"'):html.find("</script>", html.find('type="importmap"'))])
    assert refs == []


def test_vendored_files_exist():
    base = INDEX.parent / "vendor"
    for rel in ("d3.min.js", "mediabunny.min.mjs", "three/three.module.js", "three/three.core.js",
                "three/addons/postprocessing/GTAOPass.js", "fonts/inter-latin-wght-normal.woff2"):
        assert (base / rel).exists(), rel
