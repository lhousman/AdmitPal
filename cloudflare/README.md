# Admit Pal on Cloudflare

One Cloudflare Worker serves the whole app: the website (static assets) plus the API that `essay_server.py`
provides locally. That covers the live Essay Coach (streamed, with backup models and friendly errors), reading
uploaded `.txt`, `.md` and `.docx` files, and accounts. Accounts are stored in Cloudflare KV, with passwords hashed
using PBKDF2. API keys are Worker secrets and never reach the browser.

The website code (`index.html`) is identical to local: it calls the same `api/...` addresses. The coach prompt
(`coach_system.md`) and playbook (`coach_playbook.md`) are shared with the Python server and bundled into the
Worker, so they stay in sync. `build.mjs` copies only `index.html`, `simulated_responses.json` and `font/` into
`public/`, so server code, keys and saved accounts can never be deployed.

Difference from the local server: PDF text can't be read in the Worker, so the coach asks for `.docx` or `.txt`.

## Deploy (first time, about 10 minutes)
You need a free Cloudflare account (https://dash.cloudflare.com/sign-up) and Node.js 18+.

```bash
cd AdmitPal/cloudflare
npm install
npx wrangler login                              # opens your browser to connect your Cloudflare account
npx wrangler kv namespace create ACCOUNTS       # prints an id: paste it into wrangler.toml (kv_namespaces id)
npx wrangler secret put GEMINI_API_KEY          # paste your key when asked (it is stored encrypted)
npx wrangler deploy                             # prints your URL, e.g. https://admitpal.<your-subdomain>.workers.dev
```
Add other providers the same way if you have keys: `npx wrangler secret put ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
`DEEPSEEK_API_KEY`. Only providers with a key can be picked in the coach's model menu.

## Update after a change
```bash
cd AdmitPal/cloudflare && git pull && npx wrangler deploy
```
To deploy automatically on every push to GitHub instead: in the Cloudflare dashboard open **Workers & Pages >
admitpal > Settings > Builds**, connect the GitHub repo, set the root directory to `cloudflare`, the build command
to `npm install` and the deploy command to `npx wrangler deploy`.

## Run the Worker on your own machine
Create `cloudflare/.dev.vars` (git-ignored) with your key, then start it:
```
GEMINI_API_KEY=your-key
```
```bash
cd AdmitPal/cloudflare && npx wrangler dev       # http://localhost:8787
```
For testing without any key or cost, put `ADMITPAL_MOCK=1` in `.dev.vars` (add `ADMITPAL_MOCK_BUSY=1` to simulate
an overloaded model and watch the backup model take over). Never set these in production.

## Settings
In `wrangler.toml` under `[vars]`: `ADMITPAL_DEFAULT` (provider the menu starts on), and optionally
`ADMITPAL_GEMINI_MODEL`, `ADMITPAL_GEMINI_FALLBACKS` (comma-separated backup models), `ADMITPAL_TEMPERATURE`,
`ADMITPAL_PLAYBOOK_CHARS`. Model names use the same format as locally, for example `gemini/gemini-flash-latest`.

## Logs
`npx wrangler tail` streams the Worker's logs: which model answered, which playbook sections were sent, and the
technical detail of any provider error (users only see the friendly message).
