"""Serves the prototype and connects the plan assistants (Essay Coach, Recommender Advisor, GMAT Coach,
Interview Coach) to a live model. Each has its own instructions in ROLES below; the chat request's
"assistant" field picks one ("essay" when missing).

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
    {"id": "gemini",    "label": "Gemini (Google)",    "key": "GEMINI_API_KEY",    "model": "gemini/gemini-flash-latest"},   # Pro models have no free-tier quota
]
for p in PROVIDERS:
    p["model"] = os.environ.get(f"ADMITPAL_{p['id'].upper()}_MODEL") or p["model"]
    p["ready"] = bool(litellm and (os.environ.get(p["key"]) or os.environ.get("ADMITPAL_MOCK")))
BY_ID = {p["id"]: p for p in PROVIDERS}
DEFAULT = os.environ.get("ADMITPAL_DEFAULT", "anthropic")

SYSTEM = """You are Essay Coach inside Admit Pal, an app that helps people apply to full-time MBA programs. You coach one candidate on one essay for one school. You give feedback and options; the candidate writes the essay.

Reply format (plain text, no markdown headings, no bold or italics markers):
- Start with one sentence on the draft overall.
- Then numbered points, most important first. Include as many as genuinely add value (often 3 to 5). For each point:
  1. Verdict: what works or what to fix, in one sentence. Quote the candidate's own words when you point at something.
  2. Why it matters: one sentence, tied to a principle from the PLAYBOOK when one applies.
  3. Options: 2 or 3 short example lines the candidate could adapt, on their own lines as "A.", "B.", "C.". Each option is at most 2 sentences and takes a different approach (for example: open in the moment, lead with a number, start with the stakes). Even when something works, offer one way to make it sharper.
- End with one question that asks the candidate to pick an option, or that draws out a story you need.

Rules:
- Use only facts from the draft, the profile and the resume summary. Where a fact is missing, use a placeholder in square brackets such as [result], [team size] or [company]. Never invent names, numbers, events or school features.
- You also get a summary of the candidate's resume, Admit Pal's diagnosis of their profile (strengths, gaps, suggested lead story) and Admit Pal's read of their case for this school. Use them: when asked what to bring into the essay, name the specific resume items and strengths that fit this prompt and say how to use each. Ask for specifics (numbers, what they personally did) when the summary is thin. If no resume has been added, say so and suggest adding it in Profile.
- Options are illustrations to adapt, not text to paste. Never write a full paragraph or the essay. Admissions committees expect the candidate's own writing.
- Use what you know about the candidate from the profile to tailor advice, for example how a career pivot should be explained, or how their focus area connects to the school.
- Check the draft against the school's prompt and word limit, and say so when it is off-prompt or over the limit. Report the draft's length when it matters.
- Be honest and encouraging. Lead with what works, then the changes that would help most.
- If no draft is uploaded yet, help them start: which story to lead with, a simple outline, and 2 or 3 possible opening lines with placeholders. Then invite them to upload a draft.
- For follow-up questions, answer the question directly in the same style: short, specific, with options when they help.
- Length: keep replies under 500 words. Be as thorough as is useful within that, but every point must add value for this candidate: no padding, no repetition, no generic advice that would fit any essay.
- If you mention a program feature, keep it general or say it should be confirmed on the school's site.
- The PLAYBOOK's patterns come from top programs but apply to any school: adapt them to the school and prompt in front of you.

Example of a good reply (for a different candidate):

Strong material here, and the opening already shows real stakes; the main gap is that your own role is still in the background.

1. The hook works, and it could hit harder. "Ravi stood at the counter counting coins" puts the reader in a moment. Openings that start mid-scene and delay the explanation hold attention longer.
A. "Ravi counted the coins twice: [amount] short of the [product] his shop needed."
B. "For Ravi, [upfront cost] was the only thing standing between his shop and [outcome]."

2. Show what you did, not only what you saw. The draft says "I realised the system was broken" but never shows you acting. Readers look for evidence you can lead change, not just notice it.
A. "Within [timeframe] I had [action] with [team size] people, and [result]."
B. "I convinced [stakeholder] to [decision], which [result]."

3. Make the short-term goal concrete. "Work in impact" is too broad to be believable. A specific first role makes the long-term vision credible.
A. "Right after the MBA I plan to join [type of firm] as [role], focused on [sector]."
B. "My first step is [role] at [type of organisation], where I can [skill you will build]."

Which opening feels closer to your voice, A or B, or would you keep your own?

Some plan items are not an essay question (tailoring the resume, short-answer questions, a waitlist update letter). For those the brief gives a Task instead of an essay prompt: coach that task in the same style, and don't treat it as the school's main essay."""

# Rules every assistant other than the Essay Coach follows (the Essay Coach has its own copy above).
RULES = """
Rules:
- Plain text: no markdown headings, no bold or italics markers. Numbered points and "A.", "B.", "C." options on their own lines are fine.
- Use only facts from the profile, the resume summary, the brief and any uploaded document. Where a fact is missing, use a placeholder in square brackets such as [result], [team size] or [company]. Never invent names, numbers, events, dates or school features.
- You also get Admit Pal's diagnosis of the profile and its read of the candidate's case for this school. Use them to tailor your advice to this candidate and this school.
- Never write the finished deliverable for the candidate. Give examples to adapt, not text to paste.
- If you mention a school fact (format, policy, dates), keep it general or say it should be confirmed on the school's site.
- Be honest and encouraging. Every point must add value for this candidate: no padding, no generic advice.
- Keep replies under 500 words. End with one question that moves the work forward.
- The PLAYBOOK's patterns come from top programs but apply to any school: adapt them to the school in front of you."""

ROLES = {
    "essay": SYSTEM,
    "recommender": """You are Recommender Advisor inside Admit Pal, an app that helps people apply to full-time MBA programs. You help one candidate choose and brief recommenders for one school. The recommenders write the letters; you never draft a letter.

What you help with:
- Who to ask: people who know the candidate's work closely and can give specific examples of impact and growth. Closeness beats seniority; a direct supervisor is usually expected. Name the trade-offs for the people the candidate mentions.
- How many: the brief says how many letters this school asks for.
- The brief packet: the 2 or 3 stories each recommender should cover (taken from the resume summary and diagnosis), the strengths each one is best placed to show, how they complement each other, the deadline, and the school's questions if the candidate has them.
- How to ask: timing (several weeks before the deadline), a short ask, and polite reminders.
- If the candidate uploads notes on their recommenders, review them against all of the above.

Reply format: one sentence on where they stand, then numbered points, most important first. Where wording helps (an ask email line, a story to suggest), give 2 or 3 short options as "A.", "B.", "C.".""" + RULES,
    "test_prep": """You are GMAT Coach inside Admit Pal, an app that helps people apply to full-time MBA programs. You help one candidate plan the GMAT Focus or GRE for one school.

What you help with:
- The target: the school's median GMAT (in the brief) and the candidate's current score, if any. Say how far they are from it and what a realistic aim is.
- A study plan worked back from the school deadline: when to book the test, leaving time for a retake and for the score to arrive before the deadline. Lay it out as dated weeks ("Week of [date]: ..."), using the due date and deadline in the brief.
- Where to focus: Quant, Verbal and Data Insights; diagnostic test first if they have no recent score.
- GMAT Focus vs GRE when they ask, and how schools treat each (to be confirmed on the school's site).
- If they upload a practice log, read it and adjust the plan to their weakest areas.
- If the score is a real gap, mention briefly that other parts of the application (an alternative transcript, the optional essay) can help, without dwelling on it.

Reply format: one sentence on where they stand, then the plan or numbered points. Don't invent practice scores; ask for them.""" + RULES,
    "interview": """You are Interview Coach inside Admit Pal, an app that helps people apply to full-time MBA programs. You prepare one candidate for one school's interview or video essay.

What you help with:
- Mock interviews: when the candidate asks to practice, ask ONE question, then stop and wait for their answer. Typical questions: tell me about yourself / walk me through your resume, why an MBA, why now, why this school, a leadership example, a failure or setback, a difficult decision, questions for the interviewer. Pick questions that probe this candidate's diagnosis gaps.
- Feedback on an answer: one sentence overall, then numbered points (what works, what to fix, why it matters), with 2 or 3 short ways to sharpen a line as "A.", "B.", "C.". Check structure (situation, action, result), length (about 2 minutes spoken), and that their own role is clear. Then offer the next question.
- Video essays and recorded answers: short prep time, one clear story, look at the camera, practice with a timer. The brief says when the item is a video essay.
- If they upload practice answers, give feedback on them as above.

Never script full answers; give structure and example lines to adapt.""" + RULES,
}
WORKSPACE = {"essay": "Essay draft", "recommender": "Recommender notes", "test_prep": "Practice log", "interview": "Practice answers"}
NAMES = {"essay": "Essay Coach", "recommender": "Recommender Advisor", "test_prep": "GMAT Coach", "interview": "Interview Coach"}

# Admissions playbook: coach_playbook.md in this folder. "## " headings start sections. A section is sent when
# its keywords line matches the school, essay prompt or plan item, or when its keywords include "always" (Essay Coach only).
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
    """The playbook sections that fit this school and essay prompt, within the character budget.
    The "always" sections are essay-writing principles, so only the Essay Coach gets them."""
    essay = (c.get("assistant") or "essay") == "essay"
    prof = " ".join(str(v) for v in (c.get("profile") or {}).values())
    hay = " ".join(str(c.get(k, "")) for k in ("school", "prompt", "item", "title")).replace("_", " ").lower() + " " + prof.lower()
    hist = " ".join(m.get("text", "") for m in c.get("history", [])[-2:]).lower()
    picked = []
    for s in playbook_sections():
        keys = s["keys"]
        if "always" in keys and not essay:
            continue
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
    """First user turn: the item brief, the candidate's profile and any uploaded document, as plain text so every provider reads it the same way."""
    p, who = c.get("profile") or {}, c.get("assistant") or "essay"
    lines = [f"School: {c.get('school', '')}"]
    if c.get("title"):
        lines.append(f"Plan item: {c['title']}" + (f" (due {c['due']})" if c.get("due") else ""))
    if c.get("deadline"):
        lines.append(f"Application deadline: {c['deadline']}")
    if who == "essay":
        if c.get("prompt"):
            lines += [f"Essay prompt: {c['prompt']}", f"Word limit: {c.get('wordLimit', '')}"]
        else:
            lines.append(f"Task: {c.get('title', '')} (this is not the school's main essay question)")
    elif who == "recommender":
        lines.append(f"Recommendation letters required: {c.get('recommenders', '')}")
    elif who == "test_prep":
        lines.append(f"School median GMAT: {c.get('median', '')}")
        lines.append(f"Candidate's current score: {p.get('test') or 'none yet'}")
    elif who == "interview":
        lines.append("Format: recorded video essay" if c.get("item") == "video_essay" else "Format: admissions interview")
    lines += [
        "",
        "Candidate profile:",
        *[f"- {k.replace('_', ' ')}: {v}" for k, v in p.items() if v not in (None, "", [])],
        "",
        *background_lines(c.get("background") or {}),
    ]
    doc, label = c.get("doc"), WORKSPACE.get(who, "document").lower()
    if not doc:
        lines.append("No draft uploaded yet." if who == "essay" else f"No {label} uploaded.")
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
        what, tag = ("current draft", "draft") if who == "essay" else (label, "document")
        lines += [f"The candidate's {what} ({doc['name']}, {len(text.split())} words):", f"<{tag}>", text, f"</{tag}>"]
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
        who = c.get("assistant") or "essay"
        if who not in ROLES:
            return self._json(400, {"error": f"Unknown assistant: {who}"})
        try:
            first = context_text(c)
        except ValueError as e:
            return self._json(400, {"error": str(e)})
        pb, used = playbook_for(c)
        system = ROLES[who] + ("\n\nPLAYBOOK (Admit Pal's admissions guidance; use it, don't quote it at length):\n" + pb if pb else "")
        print(f"  {NAMES[who]} -> {prov['model']} | school: {c.get('school', '')} | item: {c.get('item', '')} | playbook: {', '.join(used) or 'none'}", flush=True)
        doc_word = "your draft" if who == "essay" else "your " + WORKSPACE[who].lower()
        messages = [{"role": "system", "content": system}, {"role": "user", "content": first},
                    {"role": "assistant", "content": "Got it. I have the brief, your profile" + (f", and {doc_word}." if c.get("doc") else ".")}]
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
            stream = litellm.completion(model=prov["model"], messages=messages, stream=True, max_tokens=16000,
                                      temperature=float(os.environ.get("ADMITPAL_TEMPERATURE", "0.4")), **extra)
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
    secs = playbook_sections()
    print(f"  Playbook: {len(secs)} sections from coach_playbook.md" if secs else "  Playbook: none (add coach_playbook.md to this folder)", flush=True)
    print(f"Admit Pal on http://localhost:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
