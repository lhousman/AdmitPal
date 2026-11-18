"""Creates admit_pal_prototype.html: index.html with simulated_responses.json and the font
pasted in, so it opens by double-click without a server. Re-run after editing the JSON."""
import json, pathlib, base64
here = pathlib.Path(__file__).parent
html = (here / "index.html").read_text()
data = json.dumps(json.loads((here / "simulated_responses.json").read_text()))
font = base64.b64encode((here / "font" / "PlusJakartaSans.woff2").read_bytes()).decode()
tag = '<script id="sim-inline" type="application/json"></script>'
assert tag in html
html = html.replace(tag, tag.replace("></script>", ">" + data.replace("</", "<\\/") + "</script>"))
html = html.replace('url("font/PlusJakartaSans.woff2")', 'url("data:font/woff2;base64,' + font + '")')
(here / "admit_pal_prototype.html").write_text(html)
print("wrote admit_pal_prototype.html")
