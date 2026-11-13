const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels = {direct:'直接检索',multi_doc:'多文档',refusal:'无依据拒答',injection:'提示注入'};
let payload;

function configCard(key, result) {
  const s = result.summary;
  const failures = Object.entries(s.failure_layers).map(([k,v]) => `<span>${esc(k)} × ${v}</span>`).join('') || '<span>无失败</span>';
  return `<article class="card"><div class="config-top"><div><div class="config-name">${esc(key)}</div><div class="meta">${esc(result.config.description)}</div></div><div class="rate ${s.pass_rate===1?'good':''}">${(s.pass_rate*100).toFixed(1)}%</div></div><div class="bar"><i style="width:${s.pass_rate*100}%"></i></div><div>${s.passed}/${s.total} 通过</div><div class="failure-tags">${failures}</div></article>`;
}

function renderSummary() {
  $('summary').innerHTML = ['baseline','improved'].map(k => configCard(k,payload[k])).join('');
  $('categories').innerHTML = `<div class="eyebrow">CATEGORY BREAKDOWN</div><h2>分类通过率</h2><table><thead><tr><th>能力类别</th><th>基线</th><th>改进</th></tr></thead><tbody>${Object.keys(labels).map(k=>{const b=payload.baseline.summary.by_category[k],i=payload.improved.summary.by_category[k];return `<tr><td>${labels[k]}</td><td>${b.passed}/${b.total}</td><td>${i.passed}/${i.total}</td></tr>`}).join('')}</tbody></table>`;
}

function renderCases() {
  const config = $('configSelect').value, category = $('categorySelect').value, status = $('statusSelect').value;
  const rows = payload[config].cases.filter(c => (category==='all'||c.category===category) && (status==='all'||(status==='passed')===c.passed));
  $('cases').innerHTML = rows.length ? rows.map(c => `<details class="case ${c.passed?'':'fail'}"><summary><table><tbody><tr class="${c.passed?'':'fail'}"><td><strong>${c.id}</strong></td><td>${labels[c.category]}</td><td>${esc(c.focus)}</td><td><span class="status ${c.passed?'pass':'fail'}">${c.passed?'通过':'失败'}</span></td></tr></tbody></table></summary><div class="detail"><p><strong>问题：</strong>${esc(c.question)}</p><p><strong>期望：</strong>${esc(c.expected)} ｜ <strong>实际：</strong>${esc(c.actual)} ｜ <strong>最高分：</strong>${c.top_score}</p><p><strong>引用：</strong>${esc(c.citations.join(', ')||'无')} ｜ <strong>失败层：</strong>${esc(c.failure_layer||'无')}</p><div class="answer">${esc(c.answer)}</div>${c.evidence.map(e=>`<div class="evidence-item"><strong>${esc(e.doc_title)} · ${esc(e.section_title)}</strong><br>${esc(e.text)}<br><small>score=${e.score}</small></div>`).join('')}</div></details>`).join('') : '<div class="empty">当前筛选没有案例</div>';
}

fetch('results.json').then(r=>{if(!r.ok)throw new Error(`HTTP ${r.status}`);return r.json()}).then(data=>{payload=data;renderSummary();['configSelect','categorySelect','statusSelect'].forEach(id=>$(id).addEventListener('change',renderCases));renderCases()}).catch(err=>{$('cases').innerHTML=`<div class="empty">结果加载失败：${esc(err.message)}。请通过 HTTP 服务打开页面，并先运行 python3 src/evaluate.py。</div>`});
