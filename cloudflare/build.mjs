// Copies only the website files into public/ (the Worker's static assets). Server code, keys and saved
// accounts are never copied, so they can't be deployed by mistake. Runs automatically on wrangler dev/deploy.
import { cpSync, rmSync, mkdirSync } from 'node:fs';
const out = new URL('./public/', import.meta.url), root = new URL('../', import.meta.url);
rmSync(out, {recursive:true, force:true}); mkdirSync(out);
for (const f of ['index.html', 'simulated_responses.json']) cpSync(new URL(f, root), new URL(f, out));
cpSync(new URL('font/', root), new URL('font/', out), {recursive:true});
console.log('public/ ready: index.html, simulated_responses.json, font/');
