# -*- coding: utf-8 -*-
"""本地看板：只用标准库 http.server，无 Flask 依赖。
用法：python -m app.app --port 8000
打开 http://127.0.0.1:8000/ ，在界面上改配置、选平台和关键词、小批量采集，
按分数看名单，点批准/跳过，导出 CSV。
批准只是改状态为 approved，不会自己发；发要用 sender --one --confirm 一条一条发。
配置改动会写回 config.yaml，旧文件备份为 config.yaml.bak。
"""
from __future__ import annotations

import argparse
import copy
import datetime
import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

PLATFORMS = ["douyin", "xiaohongshu", "bilibili", "weibo", "tieba"]
PLATFORM_LABELS = {
    "douyin": "抖音",
    "xiaohongshu": "小红书",
    "bilibili": "B站",
    "weibo": "微博",
    "tieba": "贴吧",
}

# 测试可覆盖：tests/test_config_ui.py 会把这个设为临时文件路径，
# 避免测试改写真实 config.yaml。
CONFIG_PATH_OVERRIDE = None

HTML = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>lead-radar 看板</title><style>
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;background:#f6f7f9;color:#111827;max-width:1080px;margin:0 auto;padding:24px 16px 48px;line-height:1.5}
a{color:#4f46e5}
code{background:#eef2ff;padding:1px 5px;border-radius:4px;font-size:13px}
/* 顶栏 */
header.topbar{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:18px 20px;display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between;box-shadow:0 1px 2px rgba(0,0,0,.04)}
header.topbar h1{font-size:22px;margin:0}
header.topbar .sub{color:#6b7280;font-size:13px;margin:4px 0 0}
.pill{display:inline-block;padding:4px 12px;border-radius:999px;font-size:13px;font-weight:600;background:#f3f4f6;color:#374151;border:1px solid #e5e7eb}
.pill.blue{background:#eff6ff;color:#1d4ed8;border-color:#bfdbfe}
.pill.green{background:#f0fdf4;color:#15803d;border-color:#bbf7d0}
.pill.red{background:#fef2f2;color:#b91c1c;border-color:#fecaca}
.pill.amber{background:#fffbeb;color:#b45309;border-color:#fde68a}
/* 数据卡片 */
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:16px 0}
@media(max-width:700px){.stats{grid-template-columns:repeat(2,1fr)}}
.stat{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:16px 18px;box-shadow:0 1px 2px rgba(0,0,0,.04)}
.stat .num{font-size:28px;font-weight:700;line-height:1.1}
.stat .lbl{color:#6b7280;font-size:13px;margin-top:4px}
/* 白卡片区块 */
section{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:18px 20px;margin:16px 0;box-shadow:0 1px 2px rgba(0,0,0,.04)}
section h2{font-size:17px;margin:0 0 8px;padding-left:10px;border-left:4px solid #4f46e5}
section p{color:#4b5563;font-size:14px}
label{display:block;margin:10px 0;font-size:14px}
label .cap{display:block;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#6b7280;margin-bottom:4px;font-weight:600}
input[type=text],input[type=number],textarea,select{padding:8px 10px;width:100%;border:1px solid #d1d5db;border-radius:8px;font:inherit;font-size:14px;background:#fff}
input[type=number]{width:140px}
input:focus,textarea:focus,select:focus{outline:none;border-color:#4f46e5;box-shadow:0 0 0 3px rgba(79,70,229,.15)}
input[readonly]{background:#f9fafb;color:#6b7280}
.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:4px 20px}
@media(max-width:700px){.form-grid{grid-template-columns:1fr}}
.form-grid .full{grid-column:1/-1}
.inline label{display:inline-block;margin-right:6px}
/* 按钮 */
button{font:inherit;font-size:14px;padding:8px 16px;border-radius:8px;cursor:pointer;margin-right:8px;margin-top:4px;border:1px solid #d1d5db;background:#fff;color:#111827}
button:hover{background:#f9fafb}
button.primary{background:#111827;color:#fff;border-color:#111827}
button.primary:hover{background:#1f2937}
button.danger{background:#fff;color:#b91c1c;border-color:#fca5a5}
button.danger:hover{background:#fef2f2}
button.small{padding:4px 10px;font-size:13px}
/* 关键词 chips / 平台 pill 开关 */
.chip{display:inline-flex;align-items:center;gap:4px;border:1px solid #c7d2fe;border-radius:999px;padding:3px 6px 3px 12px;margin:3px;background:#eef2ff;font-size:13px}
.chip button{margin:0;padding:0 6px;border:none;background:transparent;color:#4f46e5;font-size:15px;line-height:1}
.pill-toggle{display:inline-flex;align-items:center;gap:6px;border:1px solid #d1d5db;border-radius:999px;padding:6px 12px;margin:3px;cursor:pointer;font-size:14px;background:#fff}
.pill-toggle:has(input:checked){background:#eef2ff;border-color:#4f46e5;color:#3730a3;font-weight:600}
.pill-toggle input{accent-color:#4f46e5}
.ok{color:#15803d}.err{color:#b91c1c}
/* 代理警告 */
.banner{background:#fffbeb;border:1px solid #fde68a;color:#92400e;border-radius:8px;padding:10px 12px;font-size:14px;margin:10px 0}
.banner:empty{display:none}
/* 运行日志 */
#runLog{background:#0f172a;color:#e2e8f0;padding:12px;border-radius:8px;max-height:300px;overflow:auto;white-space:pre-wrap;font-size:13px}
/* 表格 */
table{border-collapse:collapse;width:100%;font-size:14px}
thead th{position:sticky;top:0;background:#f9fafb;text-align:left}
td,th{border-bottom:1px solid #e5e7eb;padding:8px 10px;text-align:left;vertical-align:top}
tbody tr:nth-child(even){background:#f9fafb}
td.nick{font-weight:600;white-space:nowrap}
td.cmt{max-width:340px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.score{display:inline-block;min-width:26px;text-align:center;padding:2px 8px;border-radius:999px;font-weight:700;font-size:13px}
.score-4{background:#dcfce7;color:#166534}.score-3{background:#dbeafe;color:#1e40af}
.score-2{background:#fef3c7;color:#92400e}.score-0,.score-1{background:#f3f4f6;color:#6b7280}
.empty{color:#6b7280;background:#f9fafb;border:1px dashed #d1d5db;border-radius:8px;padding:16px;text-align:center}
.muted{color:#6b7280;font-size:13px}
</style></head><body>
<header class="topbar">
<div><h1 id="hdrProduct">lead-radar</h1><p class="sub">只读采集 · 人工审核 · 不自动群发</p></div>
<span class="pill" id="hdrStatus">加载中…</span>
</header>
<div class="stats">
<div class="stat"><div class="num" id="statTotal">–</div><div class="lbl">线索总数</div></div>
<div class="stat"><div class="num" id="statPending">–</div><div class="lbl">待审队列</div></div>
<div class="stat"><div class="num" id="statHigh">–</div><div class="lbl">分数 ≥3 的线索</div></div>
<div class="stat"><div class="num" id="statPlatforms">–</div><div class="lbl">已配平台数</div></div>
</div>

<section id="config-section"><h2>配置</h2>
<p>改完点保存，会写回 config.yaml，旧文件备份为 config.yaml.bak。保存前请确认产品名和关键词。</p>
<div id="cfgMsg"></div>
<div class="form-grid">
<label class="full"><span class="cap">产品名</span><input type="text" id="cfgProduct"></label>
<label class="full"><span class="cap">产品介绍</span><textarea id="cfgIntro" rows="2"></textarea></label>
<label class="full"><span class="cap">关键词</span><span class="muted">输入一个词点添加，也可粘贴逗号分隔的多个词</span>
<div><input type="text" id="cfgKwInput" style="width:60%" placeholder="例如：手机壳"><button type="button" onclick="addKeyword()">添加</button></div>
<div id="cfgKwChips"></div></label>
<label class="full"><span class="cap">平台</span><span id="cfgPlatforms"></span></label>
<label><span class="cap">意向词（购买，逗号分隔）</span><input type="text" id="cfgBuy"></label>
<label><span class="cap">意向词（负面，逗号分隔）</span><input type="text" id="cfgNeg"></label>
<label><span class="cap">每平台最多内容数</span><input type="number" id="cfgMaxContents" min="1" max="20"></label>
<label><span class="cap">每条内容最多评论数</span><input type="number" id="cfgMaxComments" min="1" max="100"></label>
<label><span class="cap">每天每平台最多发送</span><input type="number" id="cfgMaxPerDay" min="1" max="50"></label>
<label><span class="cap">每小时每平台最多发送（1-10）</span><input type="number" id="cfgMaxPerHour" min="1" max="10"></label>
<label><span class="cap">发送间隔最短（秒）</span><input type="number" id="cfgMinDelay" min="10" max="600"></label>
<label><span class="cap">发送间隔最长（秒）</span><input type="number" id="cfgMaxDelay" min="10" max="600"></label>
<label><span class="cap">可发送时段开始（小时 0-23）</span><input type="number" id="cfgActiveStart" min="0" max="23"></label>
<label><span class="cap">可发送时段结束（小时 0-23）</span><input type="number" id="cfgActiveEnd" min="0" max="23"></label>
<label><span class="cap">采集基础等待（秒，0-10）</span><input type="number" id="cfgMaxSleep" min="0" max="10"></label>
<label><span class="cap">采集随机抖动（秒，0-10）</span><input type="number" id="cfgJitter" min="0" max="10"></label>
<label><span class="cap">采集并发数（只能是 1，调高会被拒绝）</span><input type="number" id="cfgConcurrency" min="1" max="1"></label>
<label><span class="cap">CDP 端口</span><input type="number" id="cfgCdpPort" min="1024" max="65535"></label>
<label><span class="cap">本机浏览器路径（只显示，不建议改）</span><input type="text" id="cfgBrowserPath" readonly></label>
<label class="full"><span class="cap">浏览器 / 代理</span>
<span class="pill-toggle"><input type="checkbox" id="cfgCdpMode"> CDP 模式（连本机真实 Chrome/Edge）</span>
<span class="pill-toggle"><input type="checkbox" id="cfgProxyEnable"> 开启代理</span></label>
</div>
<div id="proxyBanner" class="banner"></div>
<label><span class="cap">静态代理地址</span><input type="text" id="cfgProxyUrl" placeholder="http://user:pass@host:port，留空=不走代理"></label>
<button class="primary" onclick="saveConfig()">保存配置</button>
<button onclick="loadConfig()">重新加载</button>
</section>

<section id="run-section"><h2>采集（小批量）</h2>
<p>只做小批量：按下面选的平台和关键词各跑一轮，每平台默认最多 3 条内容、每条 20 条评论（见上方配置）。没登录会跳过并在日志里提示先扫码登录。</p>
<div id="runPlatforms"></div>
<label><span class="cap">关键词</span><select id="runKeyword" style="width:60%"></select></label>
<label><span class="cap">或一次性关键词（留空则用上面选的）</span><input type="text" id="runKeywordFree" placeholder="例如：手机壳"></label>
<div><button class="primary" onclick="startRun()">开始采集</button>
<button class="danger" onclick="stopRun()">停止</button>
<button onclick="refreshRun()">刷新状态</button></div>
<p><span id="runStatus" class="pill">未运行</span></p>
<pre id="runLog"></pre>
</section>

<section><h2>名单审核</h2>
<p>先在下面筛选，再点批准。批准后用 sender 一条一条发：<code>python -m sender.sender --one --queue-id N --confirm</code></p>
<label style="display:inline-block"><span class="cap">平台</span><select id="pf" style="width:140px"><option value="">全部</option><option>douyin</option><option>xiaohongshu</option><option>bilibili</option><option>weibo</option><option>tieba</option></select></label>
<label style="display:inline-block;margin-left:12px"><span class="cap">最低分数</span><input id="ms" type="number" value="0" min="0" max="4" style="width:60px"></label>
<button class="primary" onclick="load()">筛选</button>
<button onclick="loadQ()">看待审队列</button>
<a href="/api/export?min_score=2">导出分数≥2的 CSV</a>
<h3 style="margin:18px 0 8px">名单</h3><div id="list"></div>
<h3 style="margin:18px 0 8px">待审队列</h3><div id="queue"></div>
</section>
<script>
let cfgKeywords=[];
let runTimer=null;
const PLAT_LABEL={douyin:'抖音',xiaohongshu:'小红书',bilibili:'B站',weibo:'微博',tieba:'贴吧'};
function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function splitList(s){return String(s||'').split(/[,，、\\n]+/).map(x=>x.trim()).filter(Boolean);}
async function loadConfig(){
  const r=await fetch('/api/config'); if(!r.ok){document.getElementById('cfgMsg').innerHTML='<span class="err">加载配置失败：'+r.status+'</span>'; return;}
  const d=await r.json();
  document.getElementById('cfgProduct').value=d.product_name||'';
  document.getElementById('cfgIntro').value=d.product_intro||'';
  cfgKeywords=Array.isArray(d.keywords)?d.keywords.slice():[];
  renderKwChips();
  const pf=d.platforms||[];
  document.getElementById('cfgPlatforms').innerHTML=['douyin','xiaohongshu','bilibili','weibo','tieba'].map(p=>`<span class="pill-toggle"><input type="checkbox" class="cfgPf" value="${p}" ${pf.includes(p)?'checked':''}> ${PLAT_LABEL[p]}</span>`).join('');
  document.getElementById('hdrProduct').textContent=d.product_name||'lead-radar';
  const proxyOn=d.proxy&&d.proxy.enable_ip_proxy&&d.proxy.static_proxy_url;
  const cdpOn=d.browser&&d.browser.cdp_mode;
  const hdr=document.getElementById('hdrStatus');
  hdr.textContent='代理 '+(proxyOn?'已开':'未开')+' · CDP '+(cdpOn?'已开':'未开');
  hdr.className='pill '+(proxyOn?'green':'amber');
  document.getElementById('statPlatforms').textContent=pf.length;
  document.getElementById('cfgBuy').value=(d.intent_keywords&&d.intent_keywords.buy||[]).join('，');
  document.getElementById('cfgNeg').value=(d.intent_keywords&&d.intent_keywords.negative||[]).join('，');
  document.getElementById('cfgMaxContents').value=d.per_platform?d.per_platform.max_contents:'';
  document.getElementById('cfgMaxComments').value=d.per_platform?d.per_platform.max_comments_per_content:'';
  document.getElementById('cfgMaxPerDay').value=d.sender_limits?d.sender_limits.max_per_day_per_platform:'';
  document.getElementById('cfgMinDelay').value=d.sender_limits?d.sender_limits.min_delay_seconds:'';
  document.getElementById('cfgMaxDelay').value=d.sender_limits?d.sender_limits.max_delay_seconds:'';
  document.getElementById('cfgActiveStart').value=d.sender_limits?d.sender_limits.active_hours_start:'';
  document.getElementById('cfgActiveEnd').value=d.sender_limits?d.sender_limits.active_hours_end:'';
  document.getElementById('cfgMaxPerHour').value=d.sender_limits?d.sender_limits.max_per_hour_per_platform:'';
  document.getElementById('cfgMaxSleep').value=d.crawler?d.crawler.max_sleep_sec:'';
  document.getElementById('cfgJitter').value=d.crawler?d.crawler.jitter_sec:'';
  document.getElementById('cfgConcurrency').value=d.crawler?d.crawler.max_concurrency:'';
  document.getElementById('cfgCdpMode').checked=d.browser?!!d.browser.cdp_mode:false;
  document.getElementById('cfgCdpPort').value=d.browser?d.browser.cdp_port:'';
  document.getElementById('cfgBrowserPath').value=d.browser?d.browser.custom_browser_path||'（自动检测）':'';
  document.getElementById('cfgProxyEnable').checked=d.proxy?!!d.proxy.enable_ip_proxy:false;
  document.getElementById('cfgProxyUrl').value=d.proxy?d.proxy.static_proxy_url||'':'';
  document.getElementById('proxyBanner').textContent=(!d.proxy||!d.proxy.enable_ip_proxy||!d.proxy.static_proxy_url)?'代理未开启：当前用直连 IP。请用住宅/手机流量，不要用共享 VPN/服务器 IP。':'';
  // Run 区
  document.getElementById('runPlatforms').innerHTML=['douyin','xiaohongshu','bilibili','weibo','tieba'].map((p,i)=>`<span class="pill-toggle"><input type="checkbox" class="runPf" value="${p}" ${pf.includes(p)?'checked':''}> ${PLAT_LABEL[p]}</span>`).join('');
  const sel=document.getElementById('runKeyword');
  sel.innerHTML=cfgKeywords.map(k=>`<option value="${esc(k)}">${esc(k)}</option>`).join('');
}
function renderKwChips(){
  document.getElementById('cfgKwChips').innerHTML=cfgKeywords.map((k,i)=>`<span class="chip">${esc(k)}<button type="button" onclick="removeKeyword(${i})">×</button></span>`).join('')||'<span style="color:#666">暂无关键词，请添加 1-10 个</span>';
}
function addKeyword(){
  const inp=document.getElementById('cfgKwInput');
  const parts=splitList(inp.value);
  parts.forEach(p=>{if(p && !cfgKeywords.includes(p)) cfgKeywords.push(p);});
  inp.value=''; renderKwChips();
}
function removeKeyword(i){cfgKeywords.splice(i,1); renderKwChips();}
async function saveConfig(){
  const msg=document.getElementById('cfgMsg');
  const payload={
    product_name: document.getElementById('cfgProduct').value,
    product_intro: document.getElementById('cfgIntro').value,
    keywords: cfgKeywords,
    platforms: Array.from(document.querySelectorAll('.cfgPf:checked')).map(x=>x.value),
    per_platform:{max_contents: parseInt(document.getElementById('cfgMaxContents').value,10), max_comments_per_content: parseInt(document.getElementById('cfgMaxComments').value,10)},
    intent_keywords:{buy: splitList(document.getElementById('cfgBuy').value), negative: splitList(document.getElementById('cfgNeg').value)},
    sender_limits:{max_per_day_per_platform: parseInt(document.getElementById('cfgMaxPerDay').value,10), max_per_hour_per_platform: parseInt(document.getElementById('cfgMaxPerHour').value,10), min_delay_seconds: parseInt(document.getElementById('cfgMinDelay').value,10), max_delay_seconds: parseInt(document.getElementById('cfgMaxDelay').value,10), active_hours_start: parseInt(document.getElementById('cfgActiveStart').value,10), active_hours_end: parseInt(document.getElementById('cfgActiveEnd').value,10)},
    crawler:{max_sleep_sec: parseInt(document.getElementById('cfgMaxSleep').value,10), jitter_sec: parseInt(document.getElementById('cfgJitter').value,10), max_concurrency: parseInt(document.getElementById('cfgConcurrency').value,10)},
    browser:{cdp_mode: document.getElementById('cfgCdpMode').checked, cdp_port: parseInt(document.getElementById('cfgCdpPort').value,10)},
    proxy:{enable_ip_proxy: document.getElementById('cfgProxyEnable').checked, static_proxy_url: document.getElementById('cfgProxyUrl').value}
  };
  const r=await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const d=await r.json().catch(()=>({}));
  if(r.ok){msg.innerHTML='<span class="ok">保存成功，已备份旧配置到 config.yaml.bak</span>'; loadConfig();}
  else{msg.innerHTML='<span class="err">保存失败：'+esc(d.error||r.status)+'</span>';}
}
async function startRun(){
  const platforms=Array.from(document.querySelectorAll('.runPf:checked')).map(x=>x.value);
  const free=document.getElementById('runKeywordFree').value.trim();
  const keyword=free||document.getElementById('runKeyword').value;
  const r=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({platforms, keyword})});
  const d=await r.json().catch(()=>({}));
  if(r.status===409){document.getElementById('runStatus').textContent='已有采集在运行，请先停止或等它结束'; return;}
  if(!r.ok){document.getElementById('runStatus').textContent='开始失败：'+(d.error||r.status); return;}
  document.getElementById('runStatus').textContent='采集中…';
  if(runTimer) clearInterval(runTimer);
  runTimer=setInterval(refreshRun,3000);
  refreshRun();
}
async function stopRun(){
  await fetch('/api/run/stop',{method:'POST'});
  refreshRun();
}
async function refreshRun(){
  const r=await fetch('/api/run/status'); const d=await r.json();
  const st=document.getElementById('runStatus');
  const logText=(d.last_lines||[]).join('\\n');
  const risk=/风控|RISK_DETECTED|验证码|操作频繁/.test(logText);
  if(d.running){st.textContent='采集中：'+(d.current_platform||'')+' / '+(d.current_keyword||'')+'，开始于 '+(d.started_at||''); st.className='pill blue';}
  else if(risk){st.textContent='已停止：检测到风控，请先停下来检查日志'; st.className='pill red';}
  else if(d.started_at){st.textContent='已完成，上次开始 '+d.started_at+'，结束 '+(d.finished_at||'')+'，退出码 '+(d.exit_code==null?'':d.exit_code); st.className='pill green';}
  else{st.textContent='未运行'; st.className='pill';}
  updateStats();
  document.getElementById('runLog').textContent=(d.last_lines||[]).join('\\n');
  if(!d.running && runTimer){clearInterval(runTimer); runTimer=null; load(); loadQ();}
}
function scoreBadge(s){return `<span class="score score-${s>=4?4:s>=3?3:s>=2?2:0}">${s}</span>`;}
const EMPTY_HTML='<div class="empty">暂无数据，先去上面配好关键词跑一次小批量采集</div>';
async function updateStats(){
  try{
    const [rl,rq]=await Promise.all([fetch('/api/leads?min_score=0'),fetch('/api/queue?status=pending_review')]);
    const leads=await rl.json(); const q=await rq.json();
    document.getElementById('statTotal').textContent=Array.isArray(leads)?leads.length:0;
    document.getElementById('statPending').textContent=Array.isArray(q)?q.length:0;
    document.getElementById('statHigh').textContent=Array.isArray(leads)?leads.filter(x=>x.score>=3).length:0;
  }catch(e){}
}
async function load(){const pf=document.getElementById('pf').value,ms=document.getElementById('ms').value;
const r=await fetch(`/api/leads?platform=${encodeURIComponent(pf)}&min_score=${encodeURIComponent(ms)}`);
if(!r.ok){document.getElementById('list').innerHTML='<div class="empty">加载失败：'+esc(r.status)+'，请检查最低分数是不是 0-4 的整数</div>'; return;}
const d=await r.json();
if(!d.length){document.getElementById('list').innerHTML=EMPTY_HTML; updateStats(); return;}
document.getElementById('list').innerHTML='<table><thead><tr><th>分数</th><th>平台</th><th>昵称</th><th>评论</th><th>内容</th></tr></thead><tbody>'+d.map(x=>`<tr><td>${scoreBadge(x.score)}</td><td>${esc(PLAT_LABEL[x.platform]||x.platform)}</td><td class="nick">${esc(x.nickname||'')}</td><td class="cmt" title="${esc(x.text||'')}">${esc((x.text||'').slice(0,80))}</td><td><a href="${esc(x.content_url||'')}" target="_blank" rel="noopener">${esc((x.content_title||'').slice(0,30))}</a></td></tr>`).join('')+'</tbody></table>';
updateStats();}
async function loadQ(){const r=await fetch('/api/queue?status=pending_review');const d=await r.json();
if(!d.length){document.getElementById('queue').innerHTML=EMPTY_HTML; updateStats(); return;}
document.getElementById('queue').innerHTML='<table><thead><tr><th>ID</th><th>平台</th><th>分数</th><th>昵称</th><th>草稿</th><th>操作</th></tr></thead><tbody>'+d.map(x=>`<tr><td>${x.id}</td><td>${esc(PLAT_LABEL[x.platform]||x.platform)}</td><td>${scoreBadge(x.score)}</td><td class="nick">${esc(x.nickname||'')}</td><td class="cmt" title="${esc(x.draft_text||'')}">${esc((x.draft_text||'').slice(0,80))}</td><td><button class="small primary" onclick="act(${x.id},'approve')">批准</button><button class="small" onclick="act(${x.id},'skip')">跳过</button></td></tr>`).join('')+'</tbody></table>';
updateStats();}
async function act(id,a){await fetch(`/api/queue/${id}/${a}`,{method:'POST'});loadQ();}
loadConfig(); load(); loadQ(); refreshRun();
</script></body></html>"""


def _root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _config_path():
    if CONFIG_PATH_OVERRIDE:
        return CONFIG_PATH_OVERRIDE
    return os.path.join(_root(), "config.yaml")


def _load_raw_config():
    path = _config_path()
    if not os.path.exists(path):
        return {}
    try:
        import yaml  # type: ignore
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _split_list(value):
    """把字符串（逗号/中文逗号/顿号/换行分隔）或列表归一化为去重后的字符串列表。"""
    items = []
    if isinstance(value, str):
        raw = value.replace("，", ",").replace("、", ",").replace("\n", ",").split(",")
        items = raw
    elif isinstance(value, (list, tuple)):
        for v in value:
            if isinstance(v, str) and ("," in v or "，" in v or "、" in v):
                items.extend(v.replace("，", ",").replace("、", ",").split(","))
            else:
                items.append(v)
    else:
        return None
    out = []
    for v in items:
        s = str(v).strip()
        if s and s not in out:
            out.append(s)
    return out


def _coerce_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        s = value.strip()
        try:
            return int(s)
        except ValueError:
            return None
    return None


def _validate_config_payload(payload, existing):
    """返回 (merged_full_config, error)。error 非空时不写文件。"""
    if not isinstance(payload, dict):
        return None, "配置必须是 JSON 对象"
    merged = copy.deepcopy(existing) if isinstance(existing, dict) else {}
    # 确保嵌套节存在
    for key, default in (
        ("per_platform", {"max_contents": 3, "max_comments_per_content": 20}),
        ("intent_keywords", {"buy": [], "negative": []}),
        ("sender_limits", {"max_per_day_per_platform": 20, "max_per_hour_per_platform": 5,
                           "min_delay_seconds": 60,
                           "max_delay_seconds": 180, "active_hours_start": 9,
                           "active_hours_end": 21}),
        ("browser", {"cdp_mode": True, "cdp_port": 9222, "custom_browser_path": "",
                     "connect_existing": True, "headless": False}),
        ("proxy", {"enable_ip_proxy": False, "provider": "static",
                   "static_proxy_url": "", "pool_count": 2}),
        ("crawler", {"max_sleep_sec": 2, "jitter_sec": 3, "max_concurrency": 1}),
    ):
        if not isinstance(merged.get(key), dict):
            merged[key] = dict(default)
        else:
            base = dict(default)
            base.update(merged[key])
            merged[key] = base

    if "product_name" in payload:
        v = payload["product_name"]
        if not isinstance(v, str) or not v.strip():
            return None, "product_name 不能为空"
        merged["product_name"] = v.strip()
    elif not str(merged.get("product_name", "")).strip():
        return None, "product_name 不能为空"

    if "product_intro" in payload:
        v = payload["product_intro"]
        if not isinstance(v, str):
            return None, "product_intro 必须是字符串"
        merged["product_intro"] = v

    if "keywords" in payload:
        kw = _split_list(payload["keywords"])
        if kw is None or not (1 <= len(kw) <= 10):
            return None, "keywords 需要 1-10 个非空关键词"
        merged["keywords"] = kw
    elif not merged.get("keywords"):
        return None, "keywords 需要 1-10 个非空关键词"

    if "platforms" in payload:
        v = payload["platforms"]
        if not isinstance(v, (list, tuple)) or not v:
            return None, "platforms 至少选 1 个平台"
        plats = []
        for p in v:
            if p not in PLATFORMS:
                return None, f"platforms 含不支持的平台：{p}"
            if p not in plats:
                plats.append(p)
        merged["platforms"] = plats
    elif not merged.get("platforms"):
        return None, "platforms 至少选 1 个平台"

    if "per_platform" in payload:
        v = payload["per_platform"]
        if not isinstance(v, dict):
            return None, "per_platform 必须是对象"
        if "max_contents" in v:
            n = _coerce_int(v["max_contents"])
            if n is None or not (1 <= n <= 20):
                return None, "max_contents 必须是 1-20 的整数"
            merged["per_platform"]["max_contents"] = n
        if "max_comments_per_content" in v:
            n = _coerce_int(v["max_comments_per_content"])
            if n is None or not (1 <= n <= 100):
                return None, "max_comments_per_content 必须是 1-100 的整数"
            merged["per_platform"]["max_comments_per_content"] = n

    if "intent_keywords" in payload:
        v = payload["intent_keywords"]
        if not isinstance(v, dict):
            return None, "intent_keywords 必须是对象"
        for key in ("buy", "negative"):
            if key in v:
                lst = _split_list(v[key])
                if lst is None:
                    return None, f"intent_keywords.{key} 必须是字符串或字符串列表"
                merged["intent_keywords"][key] = lst

    if "sender_limits" in payload:
        v = payload["sender_limits"]
        if not isinstance(v, dict):
            return None, "sender_limits 必须是对象"
        sl = merged["sender_limits"]
        if "max_per_day_per_platform" in v:
            n = _coerce_int(v["max_per_day_per_platform"])
            if n is None or not (1 <= n <= 50):
                return None, "max_per_day_per_platform 必须是 1-50 的整数"
            sl["max_per_day_per_platform"] = n
        if "min_delay_seconds" in v:
            n = _coerce_int(v["min_delay_seconds"])
            if n is None or not (10 <= n <= 600):
                return None, "min_delay_seconds 必须是 10-600 的整数"
            sl["min_delay_seconds"] = n
        if "max_delay_seconds" in v:
            n = _coerce_int(v["max_delay_seconds"])
            if n is None or not (10 <= n <= 600):
                return None, "max_delay_seconds 必须是 10-600 的整数"
            sl["max_delay_seconds"] = n
        if sl["min_delay_seconds"] > sl["max_delay_seconds"]:
            return None, "min_delay_seconds 不能大于 max_delay_seconds"
        if "max_per_hour_per_platform" in v:
            n = _coerce_int(v["max_per_hour_per_platform"])
            if n is None or not (1 <= n <= 10):
                return None, "max_per_hour_per_platform 必须是 1-10 的整数"
            sl["max_per_hour_per_platform"] = n
        if "active_hours_start" in v:
            n = _coerce_int(v["active_hours_start"])
            if n is None or not (0 <= n <= 23):
                return None, "active_hours_start 必须是 0-23 的整数"
            sl["active_hours_start"] = n
        if "active_hours_end" in v:
            n = _coerce_int(v["active_hours_end"])
            if n is None or not (0 <= n <= 23):
                return None, "active_hours_end 必须是 0-23 的整数"
            sl["active_hours_end"] = n
        if sl["active_hours_start"] >= sl["active_hours_end"]:
            return None, "active_hours_start 必须小于 active_hours_end"

    if "browser" in payload:
        v = payload["browser"]
        if not isinstance(v, dict):
            return None, "browser 必须是对象"
        br = merged["browser"]
        if "cdp_mode" in v:
            if not isinstance(v["cdp_mode"], bool):
                return None, "browser.cdp_mode 必须是 true/false"
            br["cdp_mode"] = v["cdp_mode"]
        if "cdp_port" in v:
            n = _coerce_int(v["cdp_port"])
            if n is None or not (1024 <= n <= 65535):
                return None, "browser.cdp_port 必须是 1024-65535 的整数"
            br["cdp_port"] = n
        if "custom_browser_path" in v:
            if not isinstance(v["custom_browser_path"], str):
                return None, "browser.custom_browser_path 必须是字符串"
            br["custom_browser_path"] = v["custom_browser_path"]

    if "proxy" in payload:
        v = payload["proxy"]
        if not isinstance(v, dict):
            return None, "proxy 必须是对象"
        pr = merged["proxy"]
        if "enable_ip_proxy" in v:
            if not isinstance(v["enable_ip_proxy"], bool):
                return None, "proxy.enable_ip_proxy 必须是 true/false"
            pr["enable_ip_proxy"] = v["enable_ip_proxy"]
        if "static_proxy_url" in v:
            if not isinstance(v["static_proxy_url"], str):
                return None, "proxy.static_proxy_url 必须是字符串"
            pr["static_proxy_url"] = v["static_proxy_url"].strip()
        if pr.get("enable_ip_proxy") and not pr.get("static_proxy_url"):
            return None, "开启代理时必须填 static_proxy_url，否则请关闭代理"

    if "crawler" in payload:
        v = payload["crawler"]
        if not isinstance(v, dict):
            return None, "crawler 必须是对象"
        cr = merged["crawler"]
        if "max_sleep_sec" in v:
            n = _coerce_int(v["max_sleep_sec"])
            if n is None or not (0 <= n <= 10):
                return None, "crawler.max_sleep_sec 必须是 0-10 的整数"
            cr["max_sleep_sec"] = n
        if "jitter_sec" in v:
            n = _coerce_int(v["jitter_sec"])
            if n is None or not (0 <= n <= 10):
                return None, "crawler.jitter_sec 必须是 0-10 的整数"
            cr["jitter_sec"] = n
        if "max_concurrency" in v:
            n = _coerce_int(v["max_concurrency"])
            if n is None or n != 1:
                return None, "crawler.max_concurrency 只能是 1，不允许调高并发"
            cr["max_concurrency"] = 1
    return merged, None


def _dump_yaml(cfg):
    try:
        import yaml  # type: ignore
        return yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, default_flow_style=False)
    except Exception:
        # 手动回退：只写本项目已知字段
        lines = []
        lines.append(f'product_name: "{str(cfg.get("product_name", "")).replace(chr(34), chr(39))}"')
        lines.append(f'product_intro: "{str(cfg.get("product_intro", "")).replace(chr(34), chr(39))}"')
        lines.append("keywords:")
        for k in cfg.get("keywords", []):
            lines.append(f'  - "{k}"')
        lines.append("platforms:")
        for p in cfg.get("platforms", []):
            lines.append(f"  - {p}")
        pp = cfg.get("per_platform", {})
        lines.append("per_platform:")
        lines.append(f"  max_contents: {pp.get('max_contents', 3)}")
        lines.append(f"  max_comments_per_content: {pp.get('max_comments_per_content', 20)}")
        ik = cfg.get("intent_keywords", {})
        lines.append("intent_keywords:")
        lines.append("  buy:")
        for k in ik.get("buy", []):
            lines.append(f'    - "{k}"')
        lines.append("  negative:")
        for k in ik.get("negative", []):
            lines.append(f'    - "{k}"')
        sl = cfg.get("sender_limits", {})
        lines.append("sender_limits:")
        for k in ("max_per_day_per_platform", "max_per_hour_per_platform",
                  "min_delay_seconds", "max_delay_seconds",
                  "active_hours_start", "active_hours_end"):
            lines.append(f"  {k}: {sl.get(k, '')}")
        cr = cfg.get("crawler", {})
        lines.append("crawler:")
        for k in ("max_sleep_sec", "jitter_sec", "max_concurrency"):
            lines.append(f"  {k}: {cr.get(k, '')}")
        br = cfg.get("browser", {})
        lines.append("browser:")
        lines.append(f"  cdp_mode: {str(bool(br.get('cdp_mode', True))).lower()}")
        lines.append(f"  cdp_port: {br.get('cdp_port', 9222)}")
        lines.append(f"  custom_browser_path: \"{br.get('custom_browser_path', '')}\"")
        pr = cfg.get("proxy", {})
        lines.append("proxy:")
        lines.append(f"  enable_ip_proxy: {str(bool(pr.get('enable_ip_proxy', False))).lower()}")
        lines.append(f"  provider: {pr.get('provider', 'static')}")
        lines.append(f"  static_proxy_url: \"{pr.get('static_proxy_url', '')}\"")
        lines.append(f"  pool_count: {pr.get('pool_count', 2)}")
        return "\n".join(lines) + "\n"


def _write_config(merged):
    path = _config_path()
    if os.path.exists(path):
        shutil.copyfile(path, path + ".bak")
    with open(path, "w", encoding="utf-8") as f:
        f.write(_dump_yaml(merged))
    return path


# ---- 采集运行状态（内存 + data/run.log）----
_RUN_LOCK = threading.Lock()
_RUN_STATE = {
    "running": False,
    "current_platform": "",
    "current_keyword": "",
    "started_at": "",
    "finished_at": "",
    "last_lines": [],
    "exit_code": None,
    "stop_requested": False,
}
_RUN_PROC = None
_RUN_THREAD = None


def _run_log(line):
    line = (line or "").rstrip("\n")
    if not line:
        return
    with _RUN_LOCK:
        _RUN_STATE["last_lines"].append(line)
        if len(_RUN_STATE["last_lines"]) > 200:
            _RUN_STATE["last_lines"] = _RUN_STATE["last_lines"][-200:]
    try:
        log_path = os.path.join(_root(), "data", "run.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _run_worker(platforms, keyword):
    global _RUN_PROC
    last_code = 0
    try:
        for platform in platforms:
            with _RUN_LOCK:
                if _RUN_STATE["stop_requested"]:
                    break
                _RUN_STATE["current_platform"] = platform
                _RUN_STATE["current_keyword"] = keyword
            _run_log(f"开始采集 {platform} 关键词={keyword}")
            cmd = [sys.executable, "-m", "collector.run",
                   "--platform", platform, "--keyword", keyword]
            try:
                proc = subprocess.Popen(
                    cmd, cwd=_root(), stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True,
                    encoding="utf-8", errors="replace", bufsize=1,
                    env={**os.environ, "PYTHONUNBUFFERED": "1"})
            except Exception as e:
                _run_log(f"[{platform}] 启动失败：{e}")
                last_code = 2
                continue
            with _RUN_LOCK:
                _RUN_PROC = proc
            try:
                assert proc.stdout is not None
                for line in proc.stdout:
                    _run_log(line)
                    with _RUN_LOCK:
                        if _RUN_STATE["stop_requested"]:
                            try:
                                proc.terminate()
                            except Exception:
                                pass
                            break
                proc.wait(timeout=10)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
                proc.wait()
            finally:
                with _RUN_LOCK:
                    _RUN_PROC = None
            last_code = proc.returncode if proc.returncode is not None else 0
            _run_log(f"[{platform}] 退出码 {last_code}")
            with _RUN_LOCK:
                if _RUN_STATE["stop_requested"]:
                    break
    finally:
        with _RUN_LOCK:
            _RUN_STATE["running"] = False
            _RUN_STATE["current_platform"] = ""
            _RUN_STATE["finished_at"] = datetime.datetime.now().isoformat(timespec="seconds")
            _RUN_STATE["exit_code"] = last_code


def _start_run(platforms, keyword):
    global _RUN_THREAD
    with _RUN_LOCK:
        if _RUN_STATE["running"]:
            return False
        _RUN_STATE.update({
            "running": True, "current_platform": "", "current_keyword": keyword,
            "started_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "finished_at": "", "last_lines": [], "exit_code": None,
            "stop_requested": False,
        })
    _RUN_THREAD = threading.Thread(target=_run_worker, args=(list(platforms), keyword), daemon=True)
    _RUN_THREAD.start()
    return True


def _stop_run():
    with _RUN_LOCK:
        was_running = _RUN_STATE["running"]
        _RUN_STATE["stop_requested"] = True
        proc = _RUN_PROC
    if proc is not None:
        try:
            proc.terminate()
        except Exception:
            pass
    return was_running


def _run_status():
    with _RUN_LOCK:
        return {
            "running": _RUN_STATE["running"],
            "current_platform": _RUN_STATE["current_platform"],
            "current_keyword": _RUN_STATE["current_keyword"],
            "started_at": _RUN_STATE["started_at"],
            "finished_at": _RUN_STATE["finished_at"],
            "last_lines": list(_RUN_STATE["last_lines"][-50:]),
            "exit_code": _RUN_STATE["exit_code"],
        }


def _parse_min_score(q):
    """解析 ?min_score=，非法时返回 (None, 错误信息)，不再直接 int() 抛 500。

    以前 /api/leads 和 /api/export 里是 int(q.get("min_score", ["0"])[0])，
    传 ?min_score=abc 会直接 500。现在返回 400 + 明白的提示。
    """
    raw = q.get("min_score", ["0"])[0]
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None, "min_score 必须是 0-4 的整数，例如 ?min_score=2"
    if not 0 <= value <= 4:
        return None, "min_score 必须是 0-4 的整数，例如 ?min_score=2"
    return value, None


class Handler(BaseHTTPRequestHandler):
    # 测试可覆盖配置路径（与模块级 CONFIG_PATH_OVERRIDE 同义，优先用模块级）
    CONFIG_PATH = None

    def log_message(self, *a):  # 安静一点
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _conn(self):
        sys.path.insert(0, _root())
        from collector.config import load_config, resolve_db_path
        from storage.db import init_db
        cfg = load_config(_config_path())
        return cfg, init_db(resolve_db_path(cfg, _root()))

    def _read_json(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        raw = self.rfile.read(n) if n > 0 else b""
        if not raw:
            return {}, None
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as e:
            return None, f"JSON 解析失败：{e}"
        if not isinstance(data, dict):
            return None, "请求体必须是 JSON 对象"
        return data, None

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            return self._send(200, HTML, "text/html")
        if u.path == "/api/config":
            sys.path.insert(0, _root())
            from collector.config import load_config
            cfg = load_config(_config_path())
            return self._send(200, json.dumps({
                "product_name": cfg.get("product_name", ""),
                "product_intro": cfg.get("product_intro", ""),
                "keywords": cfg.get("keywords", []),
                "platforms": cfg.get("platforms", []),
                "per_platform": cfg.get("per_platform", {}),
                "intent_keywords": cfg.get("intent_keywords", {}),
                "sender_limits": cfg.get("sender_limits", {}),
                "browser": cfg.get("browser", {}),
                "proxy": cfg.get("proxy", {}),
                "crawler": cfg.get("crawler", {}),
            }, ensure_ascii=False))
        if u.path == "/api/run/status":
            return self._send(200, json.dumps(_run_status(), ensure_ascii=False))
        if u.path == "/api/leads":
            q = parse_qs(u.query)
            min_score, err = _parse_min_score(q)
            if err:
                return self._send(400, json.dumps({"error": err}, ensure_ascii=False))
            cfg, conn = self._conn()
            from storage.db import list_leads
            rows = list_leads(conn, min_score=min_score,
                              platform=q.get("platform", [""])[0])
            conn.close()
            return self._send(200, json.dumps(rows, ensure_ascii=False))
        if u.path == "/api/queue":
            q = parse_qs(u.query)
            cfg, conn = self._conn()
            from storage.db import list_queue
            rows = list_queue(conn, status=q.get("status", [""])[0])
            conn.close()
            return self._send(200, json.dumps(rows, ensure_ascii=False))
        if u.path == "/api/export":
            q = parse_qs(u.query)
            min_score, err = _parse_min_score(q)
            if err:
                return self._send(400, json.dumps({"error": err}, ensure_ascii=False))
            cfg, conn = self._conn()
            from storage.db import export_csv
            out = os.path.join(_root(), cfg.get("storage", {}).get("export_dir", "data/exports"),
                               "leads.csv")
            export_csv(conn, out, min_score=min_score)
            conn.close()
            return self._send(200, json.dumps({"exported": out}, ensure_ascii=False))
        return self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        # /api/config
        if parts == ["api", "config"]:
            payload, err = self._read_json()
            if err:
                return self._send(400, json.dumps({"error": err}, ensure_ascii=False))
            existing = _load_raw_config()
            merged, verr = _validate_config_payload(payload, existing)
            if verr:
                return self._send(400, json.dumps({"error": verr}, ensure_ascii=False))
            try:
                _write_config(merged)
            except Exception as e:
                return self._send(500, json.dumps({"error": f"写入配置失败：{e}"}, ensure_ascii=False))
            return self._send(200, json.dumps({"ok": True}, ensure_ascii=False))
        # /api/run
        if parts == ["api", "run"]:
            payload, err = self._read_json()
            if err:
                return self._send(400, json.dumps({"error": err}, ensure_ascii=False))
            platforms = payload.get("platforms") or []
            keyword = str(payload.get("keyword") or "").strip()
            if not isinstance(platforms, list) or not platforms:
                return self._send(400, json.dumps({"error": "platforms 至少选 1 个平台"}, ensure_ascii=False))
            for p in platforms:
                if p not in PLATFORMS:
                    return self._send(400, json.dumps({"error": f"不支持的平台：{p}"}, ensure_ascii=False))
            if not keyword:
                return self._send(400, json.dumps({"error": "keyword 不能为空"}, ensure_ascii=False))
            if not _start_run(platforms, keyword):
                return self._send(409, json.dumps({"error": "已有采集在运行"}, ensure_ascii=False))
            return self._send(200, json.dumps({"ok": True, "platforms": platforms, "keyword": keyword}, ensure_ascii=False))
        # /api/run/stop
        if parts == ["api", "run", "stop"]:
            _stop_run()
            return self._send(200, json.dumps({"ok": True}, ensure_ascii=False))
        # /api/queue/<id>/approve|skip|sent
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "queue":
            try:
                qid = int(parts[2])
            except ValueError:
                return self._send(400, json.dumps({"error": "bad id"}))
            action = parts[3]
            status = {"approve": "approved", "skip": "skipped", "sent": "sent"}.get(action)
            if not status:
                return self._send(400, json.dumps({"error": "bad action"}))
            cfg, conn = self._conn()
            from storage.db import update_queue_status
            update_queue_status(conn, qid, status, sent=(status == "sent"))
            conn.close()
            return self._send(200, json.dumps({"ok": True, "id": qid, "status": status}))
        return self._send(404, json.dumps({"error": "not found"}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    print(f"看板：http://{args.host}:{args.port}/  （只在本地打开，不要对外暴露）")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
