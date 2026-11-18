"""Serves the prototype and connects the Essay Coach to a live model.

    ~/.admitpal-venv/bin/python essay_server.py         # http://localhost:8010
    ~/.admitpal-venv/bin/python essay_server.py 8020    # another port

Providers are interchangeable through LiteLLM (pip install litellm pypdf): one completion() call,
and the model string ("anthropic/...", "openai/...", "deepseek/...", "gemini/...") picks the provider.
The candidate picks the model in the Essay Coach workspace; only providers with a key can be picked.

Keys and settings never reach the browser. They are read from the environment, or from admitpal.env
in this folder (KEY=value lines; the server refuses to serve it). ~/.admitpal.env is also read if present:

    ANTHROPIC_API_KEY=...       OPENAI_API_KEY=...       DEEPSEEK_API_KEY=...      GEMINI_API_KEY=...
    ADMITPAL_ANTHROPIC_MODEL=anthropic/claude-opus-5-5   (optional overrides of the model IDs below)
    ADMITPAL_OPENAI_MODEL=...   ADMITPAL_DEEPSEEK_MODEL=...   ADMITPAL_GEMINI_MODEL=...
    ADMITPAL_DEFAULT=anthropic  (which provider the picker starts on)
    ADMITPAL_MOCK=1             (testing only: every provider answers with a canned reply, no keys or cost)

Without any key the page still works: the Essay Coach falls back to the simulated replies.

Endpoints (everything else is served as a static file from this folder):
    GET  /api/essay/status    {"models": [{"id","label","ready"}], "default"}
    POST /api/essay/extract   {"name","data"(base64)} -> {"words"} for .txt/.md/.docx/.pdf
    POST /api/essay/chat      streams the coach's reply as server-sent events
"""
import base64, io, json, os, pathlib, re, sys, zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

HERE = pathlib.Path(__file__).parent
MAX_DOC_BYTES = 8 * 1024 * 1024


ENV_FILES = [HERE / "admitpal.env", pathlib.Path.home() / ".admitpal.env"]


def load_settings():
    for f in ENV_FILES:
        if not f.exists():
            continue
        for line in f.read_text().splitlines():
            k, sep, v = line.partition("=")
            k = k.strip().removeprefix("export ").strip()
            if sep and k and not k.startswith("#") and not os.environ.get(k):
                os.environ[k] = v.strip().strip('"').strip("'")


load_settings()

try:
    import litellm
    litellm.drop_params = True          # ignore settings a provider doesn't support instead of failing
except ImportError:
    litellm = None
try:
    import pypdf
except ImportError:
    pypdf = None

# One row per provider. Defaults are the current flagship IDs as best known; override them in ~/.admitpal.env.
PROVIDERS = [
    {"id": "anthropic", "label": "Claude (Anthropic)", "key": "ANTHROPIC_API_KEY", "model": "anthropic/claude-opus-5-5"},
    {"id": "openai",    "label": "GPT (OpenAI)",       "key": "OPENAI_API_KEY",    "model": "openai/gpt-5.6-sol"},
    {"id": "deepseek",  "label": "DeepSeek",           "key": "DEEPSEEK_API_KEY",  "model": "deepseek/deepseek-v4-pro"},
    {"id": "gemini",    "label": "Gemini (Google)",    "key": "GEMINI_API_KEY",    "model": "gemini/gemini-pro-latest"},
]
for p in PROVIDERS:
    p["model"] = os.environ.get(f"ADMITPAL_{p['id'].upper()}_MODEL") or p["model"]
    p["ready"] = bool(litellm and (os.environ.get(p["key"]) or os.environ.get("ADMITPAL_MOCK")))
BY_ID = {p["id"]: p for p in PROVIDERS}
DEFAULT = os.environ.get("ADMITPAL_DEFAULT", "anthropic")

SYSTEM = """You are Essay Coach inside Admit Pal, an app that helps people apply to full-time MBA programs. You are coaching one candidate on one essay for one school.

How to coach:
- Help the candidate make the essay their own, stronger work. Give specific feedback, ask questions that draw out their stories, suggest structure, and point to sentences that need work. Do not write the essay or whole paragraphs for them; admissions committees expect the candidate's own writing. Short example phrasings (a sentence at most) are fine when they illustrate a point.
- Ground feedback in the actual draft: quote the candidate's own words when you point at something. If no draft has been uploaded yet, help them get started (brainstorming, outline, which story to lead with) and invite them to upload a draft.
- Answer the prompt the school actually asked. Check the draft against it and against the word limit; report the draft's length when it matters.
- Use what you know about the candidate (profile below) to tailor advice, for example how a career pivot should be explained, or how their focus area connects to the school.
- Be honest and encouraging. Lead with what works, then the two or three changes that would help most. Don't invent facts about the school; if you mention a program feature, keep it general or say it should be confirmed on the school's site.
- Keep replies short enough to read on a phone: usually under 200 words, plain text, short paragraphs or a numbered list. No markdown headings, no bold or italics markers."""


def doc_text(name, raw):
    """Plain text from an uploaded file, or None when the format can't be read here."""
    low = name.lower()
    if low.endswith((".txt", ".md")):
        return raw.decode("utf-8", errors="replace")
    if low.endswith(".docx"):
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="replace")
        xml = re.sub(r"</w:p>", "\n", xml).replace("<w:tab/>", "\t")
        text = re.sub(r"<[^>]+>", "", xml)
        for a, b in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'"), ("&amp;", "&")):
            text = text.replace(a, b)
        return text.strip()
    if low.endswith(".pdf") and pypdf:
        reader = pypdf.PdfReader(io.BytesIO(raw))
        return "\n".join((page.extract_text() or "") for page in reader.pages).strip() or None
    return None


def context_text(c):
    """First user turn: the essay brief, the candidate's profile and the draft, as plain text so every provider reads it the same way."""
    p = c.get("profile") or {}
    lines = [
        f"School: {c.get('school', '')}",
        f"Essay prompt: {c.get('prompt', '')}",
        f"Word limit: {c.get('wordLimit', '')}",
        "",
        "Candidate profile:",
        *[f"- {k.replace('_', ' ')}: {v}" for k, v in p.items() if v not in (None, "", [])],
        "",
    ]
    doc = c.get("doc")
    if not doc:
        lines.append("No draft uploaded yet.")
        return "\n".join(lines)
    raw = base64.b64decode(doc["data"])
    if len(raw) > MAX_DOC_BYTES:
        raise ValueError("That file is too large to send (8 MB limit).")
    try:
        text = doc_text(doc["name"], raw)
    except Exception:
        text = None
    if not text:
        lines.append(f"The candidate uploaded {doc['name']}, but its text can't be read. Ask them to upload it as .docx, .txt or a text-based PDF.")
    else:
        lines += [f"The candidate's current draft ({doc['name']}, {len(text.split())} words):", "<draft>", text, "</draft>"]
    return "\n".join(lines)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(HERE), **kw)

    def log_message(self, fmt, *args):
        if "/api/" in (self.path or ""):
            super().log_message(fmt, *args)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def blocked(self):
        path = unquote(self.path.split("?", 1)[0].split("#", 1)[0]).lower()
        return ".env" in path or path.endswith(".py") or "/." in path    # never serve the key file, server code or dotfiles

    def do_GET(self):
        if self.blocked():
            return self._json(404, {"error": "Not found"})
        if self.path.startswith("/api/essay/status"):
            return self._json(200, {"default": DEFAULT, "models": [{"id": p["id"], "label": p["label"], "ready": p["ready"]} for p in PROVIDERS]})
        return super().do_GET()

    def do_HEAD(self):
        if self.blocked():
            self.send_response(404)
            self.end_headers()
            return
        return super().do_HEAD()

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            c = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._json(400, {"error": "Bad request"})
        if self.path == "/api/essay/extract":
            try:
                text = doc_text(c["name"], base64.b64decode(c["data"]))
            except Exception:
                text = None
            return self._json(200, {"words": len(text.split()) if text else None})
        if self.path == "/api/essay/chat":
            return self.chat(c)
        self._json(404, {"error": "Not found"})

    def sse(self, obj):
        self.wfile.write(b"data: " + json.dumps(obj).encode() + b"\n\n")
        self.wfile.flush()

    def chat(self, c):
        prov = BY_ID.get(c.get("model"))
        if not prov or not prov["ready"]:
            return self._json(503, {"error": "That model has no API key on the server."})
        try:
            first = context_text(c)
        except ValueError as e:
            return self._json(400, {"error": str(e)})
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": first},
                    {"role": "assistant", "content": "Got it. I have the prompt, your profile and your draft."}]
        for m in c.get("history", []):
            if m.get("role") not in ("user", "assistant") or not m.get("text"):
                continue
            if messages[-1]["role"] == m["role"]:        # keep turns alternating
                messages[-1]["content"] += "\n\n" + m["text"]
            else:
                messages.append({"role": m["role"], "content": m["text"]})
        if messages[-1]["role"] != "user":
            return self._json(400, {"error": "The last message must be the candidate's."})

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        try:
            extra = {"mock_response": f"[Mock reply from {prov['model']}] I read your message and the {len(first.split())}-word brief."} if os.environ.get("ADMITPAL_MOCK") else {}
            stream = litellm.completion(model=prov["model"], messages=messages, stream=True, max_tokens=16000, **extra)
            finish = None
            for chunk in stream:
                ch = chunk.choices[0] if chunk.choices else None
                if not ch:
                    continue
                if ch.delta and ch.delta.content:
                    self.sse({"t": ch.delta.content})
                finish = ch.finish_reason or finish
            if finish == "length":
                self.sse({"t": "\n\n(Reply cut short.)"})
            elif finish == "content_filter":
                self.sse({"error": "The model declined that request. Try rephrasing it."})
            self.sse({"done": True, "model": prov["model"]})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except litellm.exceptions.AuthenticationError:
            self.sse({"error": f"The {prov['label']} API key was rejected. Check {prov['key']}."})
        except litellm.exceptions.NotFoundError:
            self.sse({"error": f"{prov['label']} doesn't recognise the model ID {prov['model']}. Set ADMITPAL_{prov['id'].upper()}_MODEL in admitpal.env."})
        except litellm.exceptions.RateLimitError:
            self.sse({"error": f"{prov['label']} is rate limiting or out of credit. Try again shortly or pick another model."})
        except litellm.exceptions.APIConnectionError:
            self.sse({"error": f"Couldn't reach {prov['label']}. Check your internet connection."})
        except Exception as e:                               # any other provider error, shown to the candidate
            self.sse({"error": f"{prov['label']}: {str(e)[:300]}"})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8010
    if not litellm:
        print("LiteLLM is not installed, so the Essay Coach will use simulated replies. Run: pip install litellm pypdf", flush=True)
    for p in PROVIDERS:
        print(f"  {p['label']:<20} {p['model']:<34} {'ready' if p['ready'] else 'no key (' + p['key'] + ')'}", flush=True)
    print(f"Admit Pal on http://localhost:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
