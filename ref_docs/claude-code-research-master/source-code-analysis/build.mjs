#!/usr/bin/env node
// 把所有 .md 報告打包進單一 HTML，解決 file:// CORS 問題
import { readFileSync, writeFileSync, readdirSync, statSync } from 'fs';
import { join, relative } from 'path';

const REPORTS_DIR = import.meta.dirname;
const phases = readdirSync(REPORTS_DIR)
  .filter(d => d.startsWith('phase-') && statSync(join(REPORTS_DIR, d)).isDirectory())
  .sort();

// 收集所有 .md
const docs = {};
for (const phase of phases) {
  const dir = join(REPORTS_DIR, phase);
  const files = readdirSync(dir).filter(f => f.endsWith('.md')).sort();
  for (const f of files) {
    const key = `${phase}/${f}`;
    docs[key] = readFileSync(join(dir, f), 'utf-8');
  }
}

console.log(`Collected ${Object.keys(docs).length} reports from ${phases.length} phases`);

// 讀取現有 index.html 取得其 CSS 和結構靈感，但我們直接生成新的
const phaseMeta = {
  'phase-09-harness-engineering': { title: 'Phase 9: Harness Engineering 全景分析', priority: 'P0' },
  'phase-01-system-prompt': { title: 'Phase 1: System Prompt Engineering', priority: 'P0' },
  'phase-10-cost-quota': { title: 'Phase 10: 成本與額度運用機制', priority: 'P0' },
  'phase-02-tool-definitions': { title: 'Phase 2: Tool Definitions 全集', priority: 'P1' },
  'phase-03-agent-architecture': { title: 'Phase 3: Agent 架構與 Coordinator', priority: 'P1' },
  'phase-06-security-permissions': { title: 'Phase 6: 安全與權限', priority: 'P1' },
  'phase-04-skills-system': { title: 'Phase 4: Skills 系統', priority: 'P2' },
  'phase-05-memory-context': { title: 'Phase 5: Memory & Context', priority: 'P2' },
  'phase-07-api-model-architecture': { title: 'Phase 7: API & Model Architecture', priority: 'P2' },
  'phase-08-special-features': { title: 'Phase 8: 特殊功能與彩蛋', priority: 'P3' },
};

const phaseOrder = Object.keys(phaseMeta);

// Build sidebar HTML
let sidebarHtml = '';
for (const phase of phaseOrder) {
  const meta = phaseMeta[phase];
  const files = Object.keys(docs).filter(k => k.startsWith(phase + '/'));
  const badge = meta.priority === 'P0' ? ' ⭐' : '';
  sidebarHtml += `<div class="phase-group" data-phase="${phase}">`;
  sidebarHtml += `<div class="phase-header" onclick="togglePhase(this)">${meta.title}${badge} <span class="badge">${files.length}</span></div>`;
  sidebarHtml += `<div class="phase-items">`;
  for (const f of files) {
    const name = f.split('/')[1].replace('.md', '').replace(/^\d+-/, '').replace(/-/g, ' ');
    sidebarHtml += `<div class="nav-item" data-key="${f}" onclick="loadDoc('${f}')">${f.split('/')[1].replace('.md','')}</div>`;
  }
  sidebarHtml += `</div></div>`;
}

// Encode docs as base64 JSON to avoid escaping issues
const docsB64 = Buffer.from(JSON.stringify(docs)).toString('base64');

const html = `<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Claude Code CLI 原始碼逆向分析</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.1/marked.min.js"><\/script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"><\/script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/mermaid/10.9.0/mermaid.min.js"><\/script>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: -apple-system, 'Segoe UI', sans-serif; background:#0d1117; color:#c9d1d9; display:flex; height:100vh; overflow:hidden; }
#sidebar { width:320px; min-width:320px; background:#161b22; border-right:1px solid #30363d; overflow-y:auto; display:flex; flex-direction:column; }
#sidebar-header { padding:16px; border-bottom:1px solid #30363d; }
#sidebar-header h2 { font-size:14px; color:#58a6ff; margin-bottom:8px; }
#sidebar-header .stats { font-size:12px; color:#8b949e; }
#search { width:100%; padding:8px 12px; background:#0d1117; border:1px solid #30363d; border-radius:6px; color:#c9d1d9; font-size:13px; margin-top:8px; outline:none; }
#search:focus { border-color:#58a6ff; }
#nav { flex:1; overflow-y:auto; padding:8px; }
.phase-group { margin-bottom:4px; }
.phase-header { padding:8px 12px; font-size:13px; font-weight:600; color:#c9d1d9; cursor:pointer; border-radius:6px; display:flex; align-items:center; justify-content:space-between; }
.phase-header:hover { background:#1c2128; }
.badge { background:#30363d; color:#8b949e; font-size:11px; padding:2px 8px; border-radius:10px; font-weight:400; }
.phase-items { display:none; padding-left:12px; }
.phase-items.open { display:block; }
.nav-item { padding:6px 12px; font-size:12px; color:#8b949e; cursor:pointer; border-radius:4px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.nav-item:hover { background:#1c2128; color:#c9d1d9; }
.nav-item.active { background:#1f6feb33; color:#58a6ff; }
#content { flex:1; overflow-y:auto; padding:32px 48px; max-width:100%; }
#content h1 { color:#f0f6fc; border-bottom:1px solid #30363d; padding-bottom:12px; margin-bottom:16px; font-size:28px; }
#content h2 { color:#f0f6fc; margin-top:24px; margin-bottom:12px; font-size:22px; }
#content h3 { color:#c9d1d9; margin-top:20px; margin-bottom:8px; }
#content p { line-height:1.7; margin-bottom:12px; }
#content a { color:#58a6ff; }
#content code { background:#161b22; padding:2px 6px; border-radius:4px; font-size:0.9em; }
#content pre { background:#161b22; border:1px solid #30363d; border-radius:8px; padding:16px; overflow-x:auto; margin:12px 0; }
#content pre code { background:none; padding:0; }
#content table { width:100%; border-collapse:collapse; margin:12px 0; }
#content th, #content td { border:1px solid #30363d; padding:8px 12px; text-align:left; font-size:13px; }
#content th { background:#161b22; color:#f0f6fc; }
#content tr:hover { background:#161b2288; }
#content blockquote { border-left:3px solid #3b82f6; padding-left:16px; color:#8b949e; margin:12px 0; }
.welcome { text-align:center; padding-top:15vh; }
.welcome h1 { border:none; font-size:36px; margin-bottom:8px; }
.welcome p { color:#8b949e; font-size:16px; }
.welcome .cards { display:flex; flex-wrap:wrap; gap:12px; justify-content:center; margin-top:32px; max-width:700px; margin-left:auto; margin-right:auto; }
.welcome .card { background:#161b22; border:1px solid #30363d; border-radius:8px; padding:16px; width:200px; cursor:pointer; text-align:left; }
.welcome .card:hover { border-color:#58a6ff; }
.welcome .card h3 { font-size:14px; color:#58a6ff; margin-bottom:4px; }
.welcome .card p { font-size:12px; color:#8b949e; margin:0; }
#mobile-toggle { display:none; position:fixed; top:12px; left:12px; z-index:100; background:#161b22; border:1px solid #30363d; color:#c9d1d9; padding:8px 12px; border-radius:6px; cursor:pointer; font-size:16px; }
@media (max-width:768px) {
  #sidebar { position:fixed; left:-320px; z-index:99; height:100%; transition:left .3s; }
  #sidebar.open { left:0; }
  #mobile-toggle { display:block; }
  #content { padding:16px; padding-top:52px; }
}
.mermaid { background:#161b22; border-radius:8px; padding:16px; margin:12px 0; text-align:center; }
</style>
</head>
<body>
<button id="mobile-toggle" onclick="document.getElementById('sidebar').classList.toggle('open')">&#9776;</button>
<div id="sidebar">
  <div id="sidebar-header">
    <h2>Claude Code CLI 逆向分析</h2>
    <div class="stats">v2.1.88 | ${Object.keys(docs).length} 份報告 | ${phases.length} 個領域</div>
    <input id="search" type="text" placeholder="搜尋報告..." oninput="filterNav(this.value)">
  </div>
  <div id="nav">${sidebarHtml}</div>
</div>
<div id="content">
  <div class="welcome">
    <h1>Claude Code CLI 原始碼逆向分析</h1>
    <p>基於 v2.1.88 npm sourcemap 洩漏 (2026-03-31) — ${Object.keys(docs).length} 份分類報告</p>
    <div class="cards">
      <div class="card" onclick="loadDoc('phase-09-harness-engineering/01-agent-loop-analysis.md')"><h3>⭐ Harness Engineering</h3><p>Agent Loop、Context Engineering、Tool Orchestration</p></div>
      <div class="card" onclick="loadDoc('phase-01-system-prompt/01-main-system-prompt.md')"><h3>⭐ System Prompt</h3><p>完整系統提示詞逆向</p></div>
      <div class="card" onclick="loadDoc('phase-10-cost-quota/01-cost-tracking-architecture.md')"><h3>⭐ 成本機制</h3><p>Cost Envelope、Rate Limiting</p></div>
      <div class="card" onclick="loadDoc('phase-06-security-permissions/01-security-architecture-overview.md')"><h3>安全與權限</h3><p>七層縱深防禦架構</p></div>
      <div class="card" onclick="loadDoc('phase-03-agent-architecture/01-agent-system-overview.md')"><h3>Agent 架構</h3><p>Subagent、Coordinator、Swarm</p></div>
      <div class="card" onclick="loadDoc('phase-08-special-features/08-feature-flags.md')"><h3>隱藏功能</h3><p>82 個 Feature Flags + KAIROS</p></div>
    </div>
  </div>
</div>
<script>
const DOCS = JSON.parse(new TextDecoder().decode(Uint8Array.from(atob("${docsB64}"),c=>c.charCodeAt(0))));
mermaid.initialize({ theme:'dark', startOnLoad:false });
marked.setOptions({ highlight:(code,lang)=>{ try{return lang?hljs.highlight(code,{language:lang}).value:hljs.highlightAuto(code).value}catch(e){return code} } });

function loadDoc(key) {
  const md = DOCS[key];
  if (!md) return;
  const el = document.getElementById('content');
  el.innerHTML = marked.parse(md);
  el.scrollTop = 0;
  // render mermaid
  el.querySelectorAll('pre code.language-mermaid').forEach((block,i)=>{
    const div = document.createElement('div');
    div.className = 'mermaid';
    div.textContent = block.textContent;
    block.closest('pre').replaceWith(div);
  });
  try { mermaid.run({ nodes: el.querySelectorAll('.mermaid') }); } catch(e){}
  // highlight remaining code
  el.querySelectorAll('pre code').forEach(b => hljs.highlightElement(b));
  // update active state
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const active = document.querySelector('.nav-item[data-key="'+key+'"]');
  if (active) { active.classList.add('active'); active.closest('.phase-items')?.classList.add('open'); }
  location.hash = key;
  document.getElementById('sidebar').classList.remove('open');
}

function togglePhase(el) {
  el.nextElementSibling.classList.toggle('open');
}

function filterNav(q) {
  q = q.toLowerCase();
  document.querySelectorAll('.nav-item').forEach(n => {
    n.style.display = n.dataset.key.toLowerCase().includes(q) ? '' : 'none';
  });
  document.querySelectorAll('.phase-items').forEach(p => {
    const hasVisible = [...p.children].some(c => c.style.display !== 'none');
    p.classList.toggle('open', hasVisible && q.length > 0);
    p.closest('.phase-group').style.display = hasVisible || !q ? '' : 'none';
  });
}

// hash routing
if (location.hash.length > 1) loadDoc(location.hash.slice(1));
window.addEventListener('hashchange', () => { if(location.hash.length>1) loadDoc(location.hash.slice(1)); });
<\/script>
</body>
</html>`;

writeFileSync(join(REPORTS_DIR, 'index.html'), html, 'utf-8');
console.log(`Written index.html (${(Buffer.byteLength(html)/1024).toFixed(0)}KB) with ${Object.keys(docs).length} embedded reports`);
