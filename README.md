# Admit Pal: clickable prototype (v6, merged)

This copy adds four parts from the AdmitPal prototype to the v6 prototype: resume upload and profile diagnosis, the dated action plan, the assistants with expert review, and application status with the Admitted screen. See "Merged from the AdmitPal prototype" below.

## Run it locally

You need Python 3.10 or newer (`python3 --version`) and git. API keys are optional: without one, the app runs with sample replies in the Essay Coach.

1. **Get the code.**
   ```bash
   git clone https://github.com/lhousman/AdmitPal.git
   cd AdmitPal
   ```
2. **Install the two Python packages** ([LiteLLM](https://docs.litellm.ai/) for the model providers, pypdf for reading PDF drafts) in a virtual environment inside the folder:
   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```
   On Windows use `py -m venv .venv` and `.venv\Scripts\pip install -r requirements.txt`.
3. **Add your API keys** (optional). Copy the template and paste a key after the `=` for each provider you have; leave the rest blank.
   ```bash
   cp admitpal.env.example admitpal.env
   ```
   `admitpal.env` is git-ignored, and the server refuses to serve it, so keys never reach the browser or the repo. Don't commit it, and clear the keys before zipping or sharing the folder.
4. **Start the server.**
   ```bash
   .venv/bin/python essay_server.py
   ```
   (Windows: `.venv\Scripts\python essay_server.py`.) It prints which providers are ready, then serves the app.
5. **Open http://localhost:8010.** To try it quickly, tap **I already have an account** to load a sample profile, choose schools, then open an essay item from the plan. The Essay Coach shows the school's essay question at the top and a model picker; providers without a key are greyed out.

Other ways to run it:
- **Another port:** `.venv/bin/python essay_server.py 8020`.
- **Without keys or cost:** `ADMITPAL_MOCK=1 .venv/bin/python essay_server.py` makes every provider answer with a canned reply, for testing the live coach.
- **Fully offline:** double-click `admit_pal_prototype.html`. The font and responses are built in; the Essay Coach uses the sample replies.
- **Editing app text:** `index.html` reads `simulated_responses.json` live, so a refresh shows your edits. Afterwards run `python3 build_standalone.py` to refresh the double-click version.

Stop the server with Ctrl+C. After editing `admitpal.env` or `essay_server.py`, stop and start it again.

The prototype opens as a **website** with a top navigation bar. The yellow **Prototype log and Test mode** tab on the right edge opens the tester drawer, which also has a **Phone view** button to switch to the original mobile app layout (used for the Assignment 4 screenshots).

## Happy path
1. **Welcome**: tap Get started (new user) or I already have an account (loads a returning user, Priya).
2. **Sign up** (simulated): email, Google or Apple. No account is created.
3. **Profile setup**, seven steps, each skippable: name, GMAT Focus or GRE, GPA (4.0 or 10 scale), years of experience and industry, goals (focus areas and career goal), budget and background (tuition range, company sponsorship, legacy candidate and which school), resume upload (shows a simulated "resume read" summary).
4. **Home**: tap Check my fit. School-specific advice also works; Application dashboard opens the Plan tab and Talk to an advisor opens expert review.
5. **Choose your schools**: 44 full-time programs (US, Europe, Asia, Canada), filterable by 2-year or 1-year. 12 suggestions balanced across Dream, Target and Safe, each card tagged with your fit. Suggestions recalculate whenever your profile changes.
6. **My list**: Admit Pal's read of the list, the Profile diagnosis card (strengths, gaps and story; needs a resume), Dream / Target / Safe counts and a section per bucket. Tap a school.
7. **School advice**: chance gauge, then Strengths, Weaknesses and Opportunity. "Open my plan" jumps to that school's plan.
8. **Profile tab**: edit any detail and both the list and the suggestions recalculate.
9. **Community tab**: 112 threads (14 hand-written, 98 synthetic). Sort by For you, Hot, New or Top; each sort explains itself and For you cards say why they're shown. Topic filters, search, Show more paging, up and down votes on threads and comments, live invite trackers, new posts and comments.
10. **Share a result**: anonymously (updates the tracker only) or with basic details you choose (country, gender, prior industry, optionally your score and experience). Posting with details adds your result to that school's invite thread with your chosen flair.

## Merged from the AdmitPal prototype
11. **Plan tab**: every school on the list gets dated action items worked back from its (mock) Round 2 deadline. Plans differ by school: each school has its own `requirements` (1 or 2 recommenders, 1 to 3 essays with their own prompts and word limits, and sometimes a video essay or short answers), shown as a "Requires ..." line above its items. Filter by school, check items off, or tap **Assistant**. A GMAT retake item appears only for schools where your score is below the median band; a "Take the GMAT or GRE" item appears if you have no score.
12. **Assistant workspace**: the item's title and due date, then for essay items the school's **essay question** and word limit in a card that stays pinned at the top while you scroll the chat. Below it: document upload and a chat box. Each upload is captured with its school and item (the data loop, logged as "Document captured"). Essay Coach items need an upload before completion or expert review. With `essay_server.py` running, `.txt`, `.md`, `.docx` and text-based `.pdf` files get a real word count; otherwise `.txt` and `.md` do and other formats get a simulated one. Every assistant answers with a live model when a key is set (see below); otherwise replies are keyword-matched (try "how do I start" and "review my draft"). **Mark item complete** checks it off in the plan.
13. **Talk to an advisor** (Home, or "Ask an advisor to review" in a workspace): pick a school and an item, tap **Request expert review**. A simulated expert note appears after a moment.
14. **Application status**: the status chips on the Plan tab, the school page and the "Heard back?" sheet are the same control. Submitted checks off the submit item, Interview invite adds interview prep (Interview Coach), Waitlisted adds an update letter, Admitted shows the congratulations screen. Submitted and Waitlisted do not feed the Community trackers, and Submitted does not count as a result heard back.

**Live assistants (pick the model provider).** Every plan assistant can answer with a real model instead of the keyword replies: the Essay Coach (essays, plus the resume, short-answer and waitlist-letter items, which get their own task instead of the essay question), the Recommender Advisor (who to ask and how to brief them), the GMAT Coach (a dated study plan worked back from the deadline, aimed at the school's median) and the Interview Coach (one mock question at a time, feedback on answers, video-essay tips). `essay_server.py` serves this folder and calls the model through [LiteLLM](https://docs.litellm.ai/), so Anthropic, OpenAI, DeepSeek and Gemini are interchangeable: one `completion()` call, and the model string picks the provider. The candidate picks the model from a menu in the assistant workspace; providers without a key are greyed out. The coach gets the school, the essay prompt and word limit, the profile (score, GPA, experience, industry, focus, career goal, sponsorship, legacy, positioning advice) and the uploaded draft (.txt, .md, .docx or text-based PDF, read on the server). It is told to give feedback and ask questions, not to write the essay. Each reply is logged with the model that wrote it ("Coaching exchange captured").

Setup is in **Run it locally** above. Default models: `anthropic/claude-opus-5-5`, `openai/gpt-5.6-sol`, `deepseek/deepseek-v4-pro`, `gemini/gemini-pro-latest`. To change one, add e.g. `ADMITPAL_OPENAI_MODEL=openai/gpt-6-astra` to `admitpal.env` (any LiteLLM model string works); if a provider reports the model isn't found, the error in the chat names the line to add. `ADMITPAL_DEFAULT=openai` picks which provider the menu starts on. Each assistant's instructions are in `ROLES` near the top of `essay_server.py` (the Essay Coach's is `SYSTEM`), and `context_text()` builds what it is told about the school, the plan item, the profile and any upload; restart the server after changing either. All assistants share `coach_playbook.md` (it has sections for recommenders, interviews, video essays, resumes, waitlist letters and test prep). Without the server or without keys the workspace says "Sample replies" and the keyword replies are used. Expert review is still simulated. Each reply is billed to the provider account whose key you use.

**Meter on each school row.** The bar under each school on My list shows the share of that school's plan items checked off (`planPct()`), not the chance. The chance stays as the number on the right.

**Web view: List and plan combined.** On the website layout (680px or wider) My list and Plan are one full-screen view called "List and plan". The list stays on the left; clicking a school opens a pane on the right with two tabs, **Diagnosis** (the school advice: chance, why this number, strengths, weaknesses, opportunity) and **Plan** (that school's action items, assistants and status). The X closes the pane. Opening an Assistant keeps the list on the left and shows the workspace in the same pane; its back arrow returns to the Plan tab. Phone view is unchanged: My list, the school page and the Plan tab stay separate screens. The code is `split()`, `goPlan()` and `fillPane()` in `index.html`; to turn it off, make `split()` return `false`.

**Profile details and what they do.** Focus areas, career goal, tuition range, sponsorship and legacy are set in profile setup or the Profile tab.
- *Legacy* adds `fit_rules.legacy_bonus` points to the chance at the one school named, and shows as a line in "Why this number". Nothing else changes a chance.
- *Tuition range* and *focus areas* reorder the suggested schools (`over_budget_penalty`, `focus_match_bonus`) and tag school cards "over budget" or "your focus". *Sponsorship* switches the budget check off.
- All five add lines to a school's Strengths, Weaknesses and Opportunity (`advice_rules`), and the career goal adds a gap to the profile diagnosis (`diagnosis.goal_lines`).
- Option lists are `focus_areas`, `career_goals` and `tuition_ranges`; each school has mock `tuition` and `focus` values.

Where it lives: the content is in `simulated_responses.json` under `resume`, `diagnosis`, `plan`, `assistants`, `advisor` and `admitted`, plus `deadline` and `requirements` (recommenders, essays with their prompts and word limits, extras) on each school and two extra entries in `outcomes.statuses`. The code is one block in `index.html` headed "merged from the AdmitPal prototype" (`diagnosis()`, `buildPlan()`, `planStatus()`, and the `plan`, `work`, `advisor` and `admitted` screens). Deadlines and essay prompts are illustrative; confirm them before relying on them.

## Assignment 4: failure modes and Test mode
Two failure cases are built in (see `USABILITY_SPECS.md`):
- **Scenario 1, specification (intent):** a list check fires on Check my fit when a list is all Dream or has no Likely school, and offers three better-matched schools. Suggestions show fit and the gap to each school's median.
- **Scenario 2, verification:** where few similar past applicants exist, chances show a range, a Low confidence badge and a tier held at Target, plus "Why this number" and a confirm-before-relying check with expert review.
"Safe" is now called "Likely". Trigger both cases from **Test mode** in the log panel.

## Outcome nudge
Once a list exists, Home, My list and each school page ask "Heard back from a school?". Logging results is in the applicant's own interest:
- A no-invite where we estimated 45% or more lowers this user's estimates by 5 points and suggests Round 2 schools that stay Likely.
- An invite where we estimated under 30% raises their estimates by 5 points and suggests a Dream school to aim higher.
- Results can also feed Community's live trackers (anonymous, on by default).
Every result is logged as a training label next to the prediction. Copy and rules live in `simulated_responses.json` under `outcomes`. Test mode Scenario 3 jumps straight to results season.

## Regenerating the community
`gen_threads.py` rebuilds the synthetic threads in `simulated_responses.json` from templates (titles, bodies, comments, flairs). Edit the templates or counts and run `python3 gen_threads.py`, then `python3 build_standalone.py`. Ranking knobs (decay, boosts) are in `community.ranking`.

## Network effects and the data loop
The community shows the course's network-effects argument in the product: more members means more live invite reports and better threads for everyone. Every shared result is logged as a training label (school, round, result, profile), which is the outcome data loop from Assignment 2 and the reason the predictions improve as the platform grows.

Tester shortcut: on the welcome screen (or during setup), tap **Fill sample profile** in the log.

## Where the simulated AI lives
`simulated_responses.json` holds all app copy and AI output: welcome text, setup questions, school data (illustrative, not official), the chance formula weights, bucket cutoffs, suggestion rules, list summaries and all advice text with `{placeholders}`. To connect a real model, replace `chance()`, `suggested()`, `runAssessment()`, `adviceFor()`, `diagnosis()`, `buildPlan()` and the keyword reply lookup in `screens.work` in `index.html` with API calls that return the same shapes. The assistants are already connected this way: `coachReply()` in `index.html` calls `essay_server.py`.
