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

Coaching style and knowledge: SYSTEM below sets the reply format (verdict, why, options A/B/C with placeholders,
a closing question). coach_playbook.md in this folder holds the admissions playbook; only the sections whose
"keywords:" line matches the school or essay prompt are sent (sections tagged "always" are always sent; the
section tagged "fallback" is sent for any school that has no section of its own).
    ADMITPAL_TEMPERATURE=0.4        ADMITPAL_PLAYBOOK_CHARS=24000   (optional)

Endpoints (everything else is served as a static file from this folder):
    GET  /api/essay/status    {"models": [{"id","label","ready"}], "default"}
    POST /api/essay/extract   {"name","data"(base64)} -> {"words"} for .txt/.md/.docx/.pdf
    POST /api/essay/chat      streams the coach's reply as server-sent events
"""
import base64, hashlib, hmac, io, json, os, pathlib, re, secrets, sys, zipfile
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
    {"id": "gemini",    "label": "Gemini (Google)",    "key": "GEMINI_API_KEY",    "model": "gemini/gemini-flash-latest"},   # Pro models have no free-tier quota
]
# Backup models, tried in order when the main one is overloaded or rate limited (before any text is sent).
# Override with e.g. ADMITPAL_GEMINI_FALLBACKS=gemini/gemini-flash-lite-latest,gemini/gemini-2.5-flash
FALLBACKS = {"gemini": "gemini/gemini-flash-lite-latest"}
for p in PROVIDERS:
    p["model"] = os.environ.get(f"ADMITPAL_{p['id'].upper()}_MODEL") or p["model"]
    fb = os.environ.get(f"ADMITPAL_{p['id'].upper()}_FALLBACKS", FALLBACKS.get(p["id"], ""))
    p["fallbacks"] = [m.strip() for m in fb.split(",") if m.strip() and m.strip() != p["model"]]
    p["ready"] = bool(litellm and (os.environ.get(p["key"]) or os.environ.get("ADMITPAL_MOCK")))
BY_ID = {p["id"]: p for p in PROVIDERS}
DEFAULT = os.environ.get("ADMITPAL_DEFAULT", "anthropic")

# The coach's instructions live in coach_system.md (shared with the Cloudflare Worker in cloudflare/).
SYSTEM = (HERE / "coach_system.md").read_text(encoding="utf-8").strip()

# Admissions playbook: coach_playbook.md in this folder. "## " headings start sections. A section is sent when
# its keywords line matches the school or essay prompt, or when its keywords include "always".
PLAYBOOK = HERE / "coach_playbook.md"
PLAYBOOK_CHAR_BUDGET = int(os.environ.get("ADMITPAL_PLAYBOOK_CHARS", "24000"))


def playbook_sections():
    if not PLAYBOOK.exists():
        return []
    out, cur = [], None
    for line in PLAYBOOK.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            cur = {"title": line[3:].strip(), "keys": [], "body": []}
            out.append(cur)
        elif cur is not None:
            m = re.match(r"\s*(?:<!--\s*)?keywords?:\s*(.*?)(?:\s*-->)?\s*$", line, re.I)
            if m and not cur["body"]:
                cur["keys"] = [k.strip().lower() for k in m.group(1).split(",") if k.strip()]
            else:
                cur["body"].append(line)
    return out


def playbook_for(c):
    """The playbook sections that fit this school and essay prompt, within the character budget."""
    prof = " ".join(str(v) for v in (c.get("profile") or {}).values())
    hay = " ".join(str(c.get(k, "")) for k in ("school", "prompt", "item")).lower() + " " + prof.lower()
    hist = " ".join(m.get("text", "") for m in c.get("history", [])[-2:]).lower()
    picked = []
    for s in playbook_sections():
        keys = s["keys"]
        hit = "always" in keys or ("fallback" not in keys and any(k and re.search(r"\b" + re.escape(k), hay + " " + hist) for k in keys))
        if hit:
            picked.append(s)
    if not any(s["title"].lower().startswith("school:") for s in picked):
        picked += [s for s in playbook_sections() if "fallback" in s["keys"]]   # schools without their own section
    picked.sort(key=lambda s: 0 if "always" in s["keys"] else 1)
    text, used = "", []
    for s in picked:
        block = f"## {s['title']}\n" + "\n".join(s["body"]).strip() + "\n\n"
        if len(text) + len(block) > PLAYBOOK_CHAR_BUDGET:
            continue
        text += block; used.append(s["title"])
    return text.strip(), used


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


def background_lines(b):
    """Resume summary, profile diagnosis and this school's read, as computed by the app, in labelled sections."""
    bullets = lambda items: [f"- {x}" for x in items or []]
    r, d, s = b.get("resume"), b.get("diagnosis"), b.get("school_read") or {}
    if r:
        lines = [f"Resume summary (from {r.get('file', 'their resume')}):", *bullets(r.get("summary")), ""]
    else:
        lines = ["Resume: not added yet.", ""]
    if d:
        lines += ["Admit Pal's profile diagnosis:", f"- Headline: {d.get('headline', '')}",
                  "Strengths:", *bullets(d.get("strengths")), "Gaps:", *bullets(d.get("gaps")),
                  f"Suggested lead story: {d.get('lead_story', '')}", ""]
    if any(s.values()):
        lines += ["Admit Pal's read of their case for this school:", "Strengths:", *bullets(s.get("strengths")),
                  "Weaknesses:", *bullets(s.get("weaknesses")), "Opportunity:", *bullets(s.get("opportunities")), ""]
    return lines


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
        *background_lines(c.get("background") or {}),
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
        return ".env" in path or path.endswith(".py") or "/." in path or path.startswith("/accounts")   # never serve keys, code, dotfiles or accounts

    def do_GET(self):
        if self.blocked():
            return self._json(404, {"error": "Not found"})
        if self.path.startswith("/api/essay/status"):
            return self._json(200, {"accounts": True, "default": DEFAULT, "models": [{"id": p["id"], "label": p["label"], "ready": p["ready"]} for p in PROVIDERS]})
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
            out = {"words": len(text.split()) if text else None}
            if c.get("want_text") and text:
                out["text"] = text[:30000]          # the story quest reads uploaded essays
            return self._json(200, out)
        if self.path == "/api/essay/chat":
            return self.chat(c)
        if self.path.startswith("/api/account/"):
            code, body = account_api(self.path.rsplit("/", 1)[-1], c)
            return self._json(code, body)
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
        pb, used = playbook_for(c)
        system = SYSTEM + ("\n\nPLAYBOOK (Admit Pal's admissions guidance; use it, don't quote it at length):\n" + pb if pb else "")
        print(f"  coach -> {prov['model']} | school: {c.get('school', '')} | playbook: {', '.join(used) or 'none'}", flush=True)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": first},
                    {"role": "assistant", "content": "Got it. I have the prompt, your profile" + (", and your draft." if c.get("doc") else ". No draft yet.")}]
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
        busy_msg = ("Admit Pal's coach is handling a lot of requests right now. We tried a backup model too. "
                    "Please try again in a minute, or pick another model from the menu.")
        sent, chain = False, [prov["model"]] + prov["fallbacks"]
        for i, model in enumerate(chain):
            try:
                extra = {"mock_response": f"[Mock reply from {model}] I read your message and the {len(first.split())}-word brief."} if os.environ.get("ADMITPAL_MOCK") else {}
                if os.environ.get("ADMITPAL_MOCK_BUSY") and model == prov["model"]:
                    raise litellm.exceptions.ServiceUnavailableError("mock 503: high demand", llm_provider=prov["id"], model=model)
                stream = litellm.completion(model=model, messages=messages, stream=True, max_tokens=16000,
                                          temperature=float(os.environ.get("ADMITPAL_TEMPERATURE", "0.4")), **extra)
                finish = None
                for chunk in stream:
                    ch = chunk.choices[0] if chunk.choices else None
                    if not ch:
                        continue
                    if ch.delta and ch.delta.content:
                        self.sse({"t": ch.delta.content}); sent = True
                    finish = ch.finish_reason or finish
                if finish == "length":
                    self.sse({"t": "\n\n(Reply cut short.)"})
                elif finish == "content_filter":
                    self.sse({"error": "The coach couldn't answer that one. Try rephrasing your question."})
                if model != prov["model"]:
                    print(f"  coach used backup model {model}", flush=True)
                self.sse({"done": True, "model": model})
                return
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as e:
                kind = classify(e)
                print(f"  coach error ({kind}) from {model}: {str(e)[:200]}", flush=True)     # full detail stays in Terminal
                if kind == "busy" and not sent and i < len(chain) - 1:
                    continue                                   # overloaded before any text was sent: try the next backup model
                self.sse({"error": FRIENDLY.get(kind, FRIENDLY["other"]).format(label=prov["label"], key=prov["key"], model=model, pid=prov["id"].upper())
                          if kind != "busy" else busy_msg})
                return
        self.sse({"error": busy_msg})


def classify(e):
    """Sort a provider error into a few kinds the candidate can act on."""
    ex, text = litellm.exceptions, str(e).lower()
    if isinstance(e, getattr(ex, "AuthenticationError", ())) or "api key" in text and "invalid" in text:
        return "auth"
    if isinstance(e, getattr(ex, "NotFoundError", ())):
        return "notfound"
    busy_types = tuple(t for t in (getattr(ex, n, None) for n in ("RateLimitError", "ServiceUnavailableError", "InternalServerError",
                       "Timeout", "MidStreamFallbackError", "APIConnectionError")) if t)
    if isinstance(e, busy_types) or any(w in text for w in ("503", "429", "overloaded", "high demand", "unavailable", "quota", "rate limit")):
        return "busy"
    return "other"


FRIENDLY = {
    "auth": "The coach isn't set up correctly right now (the {label} key was rejected). Please let the Admit Pal team know.",
    "notfound": "The coach's model setting needs updating ({model} wasn't found). Please let the Admit Pal team know, or pick another model from the menu.",
    "other": "Something went wrong on our side while the coach was answering. Please try again in a moment.",
}


# ===== Accounts: email + password, with everything the user did saved on the server =====
ACCOUNTS = HERE / "accounts"          # one JSON file per account; git-ignored, never served


def _acct_file(email):
    return ACCOUNTS / (hashlib.sha256(email.encode()).hexdigest()[:32] + ".json")


def _pw_hash(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000).hex()


def account_api(path, c):
    """Returns (status, body). signup / login / resume / save / logout."""
    email = str(c.get("email", "")).strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return 400, {"error": "Enter a valid email."}
    f = _acct_file(email)
    acct = json.loads(f.read_text()) if f.exists() else None
    if path == "signup":
        pw = str(c.get("password", ""))
        if acct:
            return 409, {"error": "exists"}
        if len(pw) < 6:
            return 400, {"error": "Use at least 6 characters for your password."}
        salt = secrets.token_hex(16)
        acct = {"email": email, "salt": salt, "hash": _pw_hash(pw, salt), "tokens": [], "state": None}
    elif path == "login":
        if not acct:
            return 404, {"error": "none"}
        if not hmac.compare_digest(acct["hash"], _pw_hash(str(c.get("password", "")), acct["salt"])):
            return 401, {"error": "password"}
    elif path in ("resume", "save", "logout"):
        if not acct or c.get("token") not in acct.get("tokens", []):
            return 401, {"error": "session"}
        if path == "save":
            state = c.get("state")
            if len(json.dumps(state)) > 20 * 1024 * 1024:
                return 413, {"error": "too large"}
            acct["state"] = state
            ACCOUNTS.mkdir(exist_ok=True); f.write_text(json.dumps(acct))
            return 200, {"ok": True}
        if path == "logout":
            acct["tokens"].remove(c["token"]); f.write_text(json.dumps(acct))
            return 200, {"ok": True}
        return 200, {"state": acct.get("state")}
    else:
        return 404, {"error": "Not found"}
    token = secrets.token_urlsafe(24)
    acct["tokens"] = (acct.get("tokens", []) + [token])[-10:]      # a few devices at once
    ACCOUNTS.mkdir(exist_ok=True); f.write_text(json.dumps(acct))
    return 200, {"token": token, "state": acct.get("state")}


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8010
    if not litellm:
        print("LiteLLM is not installed, so the Essay Coach will use simulated replies. Run: pip install litellm pypdf", flush=True)
    for p in PROVIDERS:
        print(f"  {p['label']:<20} {p['model']:<34} {'ready' if p['ready'] else 'no key (' + p['key'] + ')'}", flush=True)
    secs = playbook_sections()
    print(f"  Playbook: {len(secs)} sections from coach_playbook.md" if secs else "  Playbook: none (add coach_playbook.md to this folder)", flush=True)
    print(f"Admit Pal on http://localhost:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
