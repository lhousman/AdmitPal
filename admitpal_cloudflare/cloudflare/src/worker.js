/* Admit Pal on Cloudflare: one Worker serves the website (static assets) and the API that essay_server.py
   provides locally: the live Essay Coach (streamed, with backup models), file reading, and accounts (KV).
   API keys are Worker secrets (wrangler secret put GEMINI_API_KEY ...); they never reach the browser. */
import SYSTEM from '../../coach_system.md';
import PLAYBOOK from '../../coach_playbook.md';

const PROVIDERS = [
  {id:'anthropic', label:'Claude (Anthropic)', key:'ANTHROPIC_API_KEY', model:'anthropic/claude-opus-5-5'},
  {id:'openai',    label:'GPT (OpenAI)',       key:'OPENAI_API_KEY',    model:'openai/gpt-5.6-sol'},
  {id:'deepseek',  label:'DeepSeek',           key:'DEEPSEEK_API_KEY',  model:'deepseek/deepseek-v4-pro'},
  {id:'gemini',    label:'Gemini (Google)',    key:'GEMINI_API_KEY',    model:'gemini/gemini-flash-latest'},   // Pro models have no free-tier quota
];
const FALLBACKS = {gemini:'gemini/gemini-flash-lite-latest'};
const MAX_DOC_BYTES = 8 * 1024 * 1024;

function providers(env){
  return PROVIDERS.map(p => {
    const up = p.id.toUpperCase(), model = env[`ADMITPAL_${up}_MODEL`] || p.model;
    const fb = String(env[`ADMITPAL_${up}_FALLBACKS`] ?? FALLBACKS[p.id] ?? '').split(',').map(x => x.trim()).filter(x => x && x !== model);
    return {...p, model, fallbacks:fb, ready:!!(env[p.key] || env.ADMITPAL_MOCK)};
  });
}
const json = (code, obj) => new Response(JSON.stringify(obj), {status:code, headers:{'Content-Type':'application/json', 'Cache-Control':'no-store'}});

export default {
  async fetch(request, env, ctx){
    const url = new URL(request.url), path = url.pathname;
    if (!path.startsWith('/api/')) return env.ASSETS.fetch(request);
    if (request.method === 'GET' && path === '/api/essay/status') {
      const P = providers(env);
      return json(200, {accounts:!!env.ACCOUNTS, default:env.ADMITPAL_DEFAULT || 'anthropic', models:P.map(p => ({id:p.id, label:p.label, ready:p.ready}))});
    }
    if (request.method !== 'POST') return json(404, {error:'Not found'});
    let c; try { c = JSON.parse(await request.text() || '{}'); } catch(e) { return json(400, {error:'Bad request'}); }
    if (path === '/api/essay/extract') {
      let text = null; try { text = await docText(c.name, b64bytes(c.data)); } catch(e) {}
      const out = {words: text ? text.split(/\s+/).filter(Boolean).length : null};
      if (c.want_text && text) out.text = text.slice(0, 30000);
      return json(200, out);
    }
    if (path === '/api/essay/chat') return chat(c, env, ctx);
    if (path.startsWith('/api/account/')) { const [code, body] = await accountApi(path.split('/').pop(), c, env); return json(code, body); }
    return json(404, {error:'Not found'});
  }
};

/* ---------------- uploaded files ---------------- */
function b64bytes(s){ const bin = atob(s || ''); const u = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i); return u; }
async function inflateRaw(bytes){ const ds = new DecompressionStream('deflate-raw'); return new Uint8Array(await new Response(new Blob([bytes]).stream().pipeThrough(ds)).arrayBuffer()); }
async function unzipEntry(buf, wanted){            // reads one file out of a .docx (a zip) via its central directory
  const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  let eocd = -1; for (let i = buf.length - 22; i >= Math.max(0, buf.length - 66000); i--) if (dv.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
  if (eocd < 0) return null;
  let off = dv.getUint32(eocd + 16, true); const n = dv.getUint16(eocd + 10, true), dec = new TextDecoder();
  for (let k = 0; k < n; k++) {
    if (dv.getUint32(off, true) !== 0x02014b50) return null;
    const method = dv.getUint16(off + 10, true), csize = dv.getUint32(off + 20, true), nl = dv.getUint16(off + 28, true), el = dv.getUint16(off + 30, true), cl = dv.getUint16(off + 32, true), lho = dv.getUint32(off + 42, true);
    const name = dec.decode(buf.subarray(off + 46, off + 46 + nl));
    if (name === wanted) { const start = lho + 30 + dv.getUint16(lho + 26, true) + dv.getUint16(lho + 28, true), data = buf.subarray(start, start + csize);
      return method === 0 ? data : method === 8 ? inflateRaw(data) : null; }
    off += 46 + nl + el + cl;
  }
  return null;
}
async function docText(name, raw){
  const low = String(name || '').toLowerCase();
  if (/\.(txt|md)$/.test(low)) return new TextDecoder().decode(raw);
  if (low.endsWith('.docx')) {
    const x = await unzipEntry(raw, 'word/document.xml'); if (!x) return null;
    let t = new TextDecoder().decode(x).replace(/<\/w:p>/g, '\n').replace(/<w:tab\/>/g, '\t').replace(/<[^>]+>/g, '');
    for (const [a, b] of [['&lt;','<'],['&gt;','>'],['&quot;','"'],['&apos;',"'"],['&amp;','&']]) t = t.split(a).join(b);
    return t.trim() || null;
  }
  return null;                                     // PDF text extraction isn't available in the Worker: ask for .docx or .txt
}

/* ---------------- what the coach is told (mirrors context_text() in essay_server.py) ---------------- */
function backgroundLines(b){
  const bullets = items => (items || []).map(x => `- ${x}`), r = b.resume, d = b.diagnosis, s = b.school_read || {};
  let lines = r ? [`Resume summary (from ${r.file || 'their resume'}):`, ...bullets(r.summary), ''] : ['Resume: not added yet.', ''];
  if (d) lines.push("Admit Pal's profile diagnosis:", `- Headline: ${d.headline || ''}`, 'Strengths:', ...bullets(d.strengths), 'Gaps:', ...bullets(d.gaps), `Suggested lead story: ${d.lead_story || ''}`, '');
  if (Object.values(s).some(v => v && v.length)) lines.push("Admit Pal's read of their case for this school:", 'Strengths:', ...bullets(s.strengths), 'Weaknesses:', ...bullets(s.weaknesses), 'Opportunity:', ...bullets(s.opportunities), '');
  return lines;
}
async function contextText(c){
  const p = c.profile || {};
  const lines = [`School: ${c.school || ''}`, `Essay prompt: ${c.prompt || ''}`, `Word limit: ${c.wordLimit || ''}`, '', 'Candidate profile:',
    ...Object.entries(p).filter(([, v]) => v !== null && v !== undefined && v !== '' && !(Array.isArray(v) && !v.length)).map(([k, v]) => `- ${k.replace(/_/g, ' ')}: ${v}`), '',
    ...backgroundLines(c.background || {})];
  const doc = c.doc;
  if (!doc) { lines.push('No draft uploaded yet.'); return lines.join('\n'); }
  const raw = b64bytes(doc.data);
  if (raw.length > MAX_DOC_BYTES) throw new Error('That file is too large to send (8 MB limit).');
  let text = null; try { text = await docText(doc.name, raw); } catch(e) {}
  if (!text) lines.push(`The candidate uploaded ${doc.name}, but its text can't be read here. Ask them to upload it as .docx or .txt.`);
  else lines.push(`The candidate's current draft (${doc.name}, ${text.split(/\s+/).filter(Boolean).length} words):`, '<draft>', text, '</draft>');
  return lines.join('\n');
}

/* ---------------- playbook sections (mirrors playbook_for() in essay_server.py) ---------------- */
const SECTIONS = (() => { const out = []; let cur = null;
  for (const line of PLAYBOOK.split(/\r?\n/)) {
    if (line.startsWith('## ')) { cur = {title:line.slice(3).trim(), keys:[], body:[]}; out.push(cur); continue; }
    if (!cur) continue;
    const m = line.match(/^\s*(?:<!--\s*)?keywords?:\s*(.*?)(?:\s*-->)?\s*$/i);
    if (m && !cur.body.length) cur.keys = m[1].split(',').map(k => k.trim().toLowerCase()).filter(Boolean); else cur.body.push(line);
  } return out; })();
const esc = k => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
function playbookFor(c, budget){
  const prof = Object.values(c.profile || {}).map(String).join(' ');
  const hay = (['school', 'prompt', 'item'].map(k => String(c[k] || '')).join(' ') + ' ' + prof).toLowerCase();
  const hist = (c.history || []).slice(-2).map(m => m.text || '').join(' ').toLowerCase(), all = hay + ' ' + hist;
  let picked = SECTIONS.filter(s => s.keys.includes('always') || (!s.keys.includes('fallback') && s.keys.some(k => new RegExp('\\b' + esc(k)).test(all))));
  if (!picked.some(s => s.title.toLowerCase().startsWith('school:'))) picked = picked.concat(SECTIONS.filter(s => s.keys.includes('fallback')));
  picked.sort((a, b) => (a.keys.includes('always') ? 0 : 1) - (b.keys.includes('always') ? 0 : 1));
  let text = ''; const used = [];
  for (const s of picked) { const block = `## ${s.title}\n` + s.body.join('\n').trim() + '\n\n'; if (text.length + block.length > budget) continue; text += block; used.push(s.title); }
  return [text.trim(), used];
}

/* ---------------- the live coach ---------------- */
const FRIENDLY = {
  busy:"Admit Pal's coach is handling a lot of requests right now. We tried a backup model too. Please try again in a minute, or pick another model from the menu.",
  auth:"The coach isn't set up correctly right now (the {label} key was rejected). Please let the Admit Pal team know.",
  notfound:"The coach's model setting needs updating ({model} wasn't found). Please let the Admit Pal team know, or pick another model from the menu.",
  other:"Something went wrong on our side while the coach was answering. Please try again in a moment.",
};
class ProviderError extends Error { constructor(kind, detail){ super(detail); this.kind = kind; } }
const kindFor = status => status === 401 || status === 403 ? 'auth' : status === 404 ? 'notfound' : (status === 429 || status >= 500) ? 'busy' : 'other';

async function chat(c, env, ctx){
  const P = providers(env), prov = P.find(p => p.id === c.model);
  if (!prov || !prov.ready) return json(503, {error:'That model has no API key on the server.'});
  let first; try { first = await contextText(c); } catch(e) { return json(400, {error:e.message}); }
  const [pb, used] = playbookFor(c, Number(env.ADMITPAL_PLAYBOOK_CHARS || 24000));
  const system = SYSTEM.trim() + (pb ? "\n\nPLAYBOOK (Admit Pal's admissions guidance; use it, don't quote it at length):\n" + pb : '');
  console.log(`coach -> ${prov.model} | school: ${c.school || ''} | playbook: ${used.join(', ') || 'none'}`);
  const messages = [{role:'user', content:first}, {role:'assistant', content:'Got it. I have the prompt, your profile' + (c.doc ? ', and your draft.' : '. No draft yet.')}];
  for (const m of c.history || []) {
    if (!['user', 'assistant'].includes(m.role) || !m.text) continue;
    if (messages[messages.length - 1].role === m.role) messages[messages.length - 1].content += '\n\n' + m.text; else messages.push({role:m.role, content:m.text});
  }
  if (messages[messages.length - 1].role !== 'user') return json(400, {error:"The last message must be the candidate's."});

  const {readable, writable} = new TransformStream(), w = writable.getWriter(), enc = new TextEncoder();
  const send = o => w.write(enc.encode('data: ' + JSON.stringify(o) + '\n\n'));
  ctx.waitUntil((async () => {
    const chain = [prov.model, ...prov.fallbacks]; let sent = false;
    try {
      for (let i = 0; i < chain.length; i++) {
        const model = chain[i];
        try {
          const finish = await streamModel(prov, model, system, messages, first, env, t => { sent = true; return send({t}); });
          if (finish === 'length') await send({t:'\n\n(Reply cut short.)'});
          if (finish === 'content_filter') await send({error:"The coach couldn't answer that one. Try rephrasing your question."});
          if (model !== prov.model) console.log(`coach used backup model ${model}`);
          await send({done:true, model}); return;
        } catch(e) {
          const kind = e.kind || 'busy';
          console.log(`coach error (${kind}) from ${model}: ${String(e.message).slice(0, 200)}`);
          if (kind === 'busy' && !sent && i < chain.length - 1) continue;
          await send({error:(FRIENDLY[kind] || FRIENDLY.other).replace('{label}', prov.label).replace('{model}', model)}); return;
        }
      }
    } finally { await w.close(); }
  })());
  return new Response(readable, {headers:{'Content-Type':'text/event-stream', 'Cache-Control':'no-store'}});
}

async function* sseLines(res){
  const reader = res.body.getReader(), dec = new TextDecoder(); let buf = '';
  for (;;) { const {value, done} = await reader.read(); if (done) break; buf += dec.decode(value, {stream:true});
    let i; while ((i = buf.indexOf('\n')) >= 0) { const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1); if (line.startsWith('data:')) { const d = line.slice(5).trim(); if (d && d !== '[DONE]') { try { yield JSON.parse(d); } catch(e) {} } } } }
}
async function streamModel(prov, model, system, messages, first, env, onText){
  const id = model.includes('/') ? model.split('/').slice(1).join('/') : model, key = env[prov.key];
  const temperature = Number(env.ADMITPAL_TEMPERATURE || 0.4);
  if (env.ADMITPAL_MOCK) {
    if (env.ADMITPAL_MOCK_BUSY && model === prov.model) throw new ProviderError('busy', 'mock 503: high demand');
    for (const t of `[Mock reply from ${model}] I read your message and the ${first.split(/\s+/).length}-word brief.`.match(/.{1,24}/g)) await onText(t);
    return 'stop';
  }
  let res;
  try {
    if (prov.id === 'anthropic') res = await fetch('https://api.anthropic.com/v1/messages', {method:'POST', headers:{'x-api-key':key, 'anthropic-version':'2023-06-01', 'content-type':'application/json'},
      body:JSON.stringify({model:id, max_tokens:16000, temperature, system, messages, stream:true})});
    else if (prov.id === 'gemini') res = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(id)}:streamGenerateContent?alt=sse`, {method:'POST', headers:{'x-goog-api-key':key, 'content-type':'application/json'},
      body:JSON.stringify({systemInstruction:{parts:[{text:system}]}, contents:messages.map(m => ({role:m.role === 'assistant' ? 'model' : 'user', parts:[{text:m.content}]})), generationConfig:{maxOutputTokens:16000, temperature}})});
    else { const url = prov.id === 'deepseek' ? 'https://api.deepseek.com/chat/completions' : 'https://api.openai.com/v1/chat/completions';
      res = await fetch(url, {method:'POST', headers:{authorization:`Bearer ${key}`, 'content-type':'application/json'},
        body:JSON.stringify({model:id, messages:[{role:'system', content:system}, ...messages], stream:true, ...(prov.id === 'deepseek' ? {temperature} : {})})}); }
  } catch(e) { throw new ProviderError('busy', 'connection: ' + e.message); }
  if (!res.ok) throw new ProviderError(kindFor(res.status), `HTTP ${res.status}: ${(await res.text()).slice(0, 300)}`);
  let finish = null;
  for await (const ev of sseLines(res)) {
    if (prov.id === 'anthropic') {
      if (ev.type === 'content_block_delta' && ev.delta && ev.delta.text) await onText(ev.delta.text);
      else if (ev.type === 'message_delta' && ev.delta && ev.delta.stop_reason) finish = ev.delta.stop_reason === 'max_tokens' ? 'length' : 'stop';
      else if (ev.type === 'error') throw new ProviderError(/overload|rate/i.test(JSON.stringify(ev)) ? 'busy' : 'other', JSON.stringify(ev));
    } else if (prov.id === 'gemini') {
      const cand = (ev.candidates || [])[0]; if (!cand) continue;
      for (const part of (cand.content && cand.content.parts) || []) if (part.text) await onText(part.text);
      if (cand.finishReason) finish = cand.finishReason === 'MAX_TOKENS' ? 'length' : cand.finishReason === 'SAFETY' ? 'content_filter' : 'stop';
    } else {
      const ch = (ev.choices || [])[0]; if (!ch) continue;
      if (ch.delta && ch.delta.content) await onText(ch.delta.content);
      if (ch.finish_reason) finish = ch.finish_reason;
    }
  }
  return finish;
}

/* ---------------- accounts (mirrors account_api() in essay_server.py, stored in KV) ---------------- */
const hex = buf => [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('');
const sha256 = async t => hex(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(t)));
const randHex = n => hex(crypto.getRandomValues(new Uint8Array(n)));
async function pwHash(pw, salt){
  const k = await crypto.subtle.importKey('raw', new TextEncoder().encode(pw), 'PBKDF2', false, ['deriveBits']);
  return hex(await crypto.subtle.deriveBits({name:'PBKDF2', hash:'SHA-256', salt:new TextEncoder().encode(salt), iterations:100000}, k, 256));   // 100k is the Workers maximum
}
function same(a, b){ if (a.length !== b.length) return false; let r = 0; for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i); return r === 0; }
async function accountApi(action, c, env){
  if (!env.ACCOUNTS) return [503, {error:'Accounts are not configured on this server.'}];
  const email = String(c.email || '').trim().toLowerCase();
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return [400, {error:'Enter a valid email.'}];
  const key = 'acct:' + (await sha256(email)).slice(0, 32);
  let acct = await env.ACCOUNTS.get(key, 'json');
  const put = () => env.ACCOUNTS.put(key, JSON.stringify(acct));
  if (action === 'signup') {
    if (acct) return [409, {error:'exists'}];
    const pw = String(c.password || ''); if (pw.length < 6) return [400, {error:'Use at least 6 characters for your password.'}];
    const salt = randHex(16); acct = {email, salt, hash:await pwHash(pw, salt), tokens:[], state:null};
  } else if (action === 'login') {
    if (!acct) return [404, {error:'none'}];
    if (!same(acct.hash, await pwHash(String(c.password || ''), acct.salt))) return [401, {error:'password'}];
  } else if (['resume', 'save', 'logout'].includes(action)) {
    if (!acct || !(acct.tokens || []).includes(c.token)) return [401, {error:'session'}];
    if (action === 'save') { const st = JSON.stringify(c.state ?? null); if (st.length > 20 * 1024 * 1024) return [413, {error:'too large'}]; acct.state = c.state; await put(); return [200, {ok:true}]; }
    if (action === 'logout') { acct.tokens = acct.tokens.filter(t => t !== c.token); await put(); return [200, {ok:true}]; }
    return [200, {state:acct.state}];
  } else return [404, {error:'Not found'}];
  const token = randHex(24); acct.tokens = [...(acct.tokens || []), token].slice(-10); await put();
  return [200, {token, state:acct.state}];
}
