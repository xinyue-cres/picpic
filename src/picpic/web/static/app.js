const state = {
  tab: 'candidates',
  photos: [],
  selected: new Set(),
  reasons: new Set(['screenshot', 'blurry', 'exact_dup']),
  blurThreshold: 100,
  label: null,
  minScore: 0.25,
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

function toggleControls() {
  const rf = document.querySelector('#reason-filters');
  const bc = document.querySelector('#blur-control');
  const lc = document.querySelector('#label-control');
  if (rf) rf.hidden = state.tab !== 'candidates';
  if (bc) bc.hidden = state.tab !== 'candidates';
  if (lc) lc.hidden = state.tab !== 'labeled';
}

async function refreshLabelSelect() {
  const info = await api(`/api/labels?min_score=${state.minScore}`);
  const sel = $('#label-select');
  const prev = sel.value;
  sel.innerHTML = '';
  if (!info.available) {
    $('#grid').innerHTML =
      '<p class="empty">运行 <code>picpic analyze --clip</code> 生成语义标签</p>';
    return false;
  }
  const total = info.categories.reduce((s, c) => s + c.count, 0) + info.unclassified_count;
  const all = document.createElement('option');
  all.value = '';
  all.textContent = `全部 (${total})`;
  sel.appendChild(all);
  for (const c of info.categories) {
    if (c.count > 0) {
      const o = document.createElement('option');
      o.value = c.name;
      o.textContent = `${c.name} (${c.count})`;
      sel.appendChild(o);
    }
  }
  if (info.unclassified_count > 0) {
    const un = document.createElement('option');
    un.value = '未分类';
    un.textContent = `未分类 (${info.unclassified_count})`;
    sel.appendChild(un);
  }
  sel.value = prev;
  state.label = sel.value || null;
  return true;
}

async function load() {
  toggleControls();
  if (state.tab === 'labeled') {
    const ready = await refreshLabelSelect();
    if (!ready) {
      state.photos = [];
      state.selected.clear();
      render();
      return;
    }
  }
  const params = new URLSearchParams({ tab: state.tab });
  if (state.tab === 'candidates' && state.blurThreshold !== 100) {
    params.set('min_blur', state.blurThreshold);
  }
  if (state.tab === 'labeled') {
    params.set('min_score', state.minScore);
    if (state.label) params.set('label', state.label);
  }
  const { photos } = await api(`/api/photos?${params}`);
  state.photos = photos;
  state.selected.clear();
  render();
}

function render() {
  const grid = $('#grid');
  grid.innerHTML = '';

  const filtered = state.tab === 'candidates'
    ? state.photos.filter(p => state.reasons.has(p.verdict_reason))
    : state.photos;

  if (state.tab === 'similar') {
    const groups = new Map();
    for (const p of filtered) {
      if (!groups.has(p.dup_group)) groups.set(p.dup_group, []);
      groups.get(p.dup_group).push(p);
    }
    for (const [gid, members] of groups) {
      const row = document.createElement('div');
      row.className = 'group';
      row.dataset.group = gid;
      for (const p of members) row.appendChild(cardFor(p));
      grid.appendChild(row);
    }
  } else {
    for (const p of filtered) grid.appendChild(cardFor(p));
  }

  $('#selected-count').textContent = `已选 ${state.selected.size} 张`;
  const primary = $('#btn-primary');
  const secondary = $('#btn-secondary');
  if (state.tab === 'trashed') {
    primary.textContent = '还原选中';
    secondary.hidden = false;
    secondary.textContent = '清空回收区';
  } else {
    primary.textContent = '移入回收区';
    secondary.hidden = true;
  }
}

function cardFor(p) {
  const el = document.createElement('div');
  el.className = 'card' + (state.selected.has(p.id) ? ' selected' : '');
  el.dataset.id = p.id;
  let badge = '';
  if (state.tab === 'labeled' && p.top_label) {
    badge = `<div class="badge label">${p.top_label.name} ${p.top_label.score.toFixed(2)}</div>`;
    if (p.clip_labels && p.clip_labels.length > 1) {
      el.title = p.clip_labels
        .slice(1)
        .map(l => `${l.name} ${l.score.toFixed(2)}`)
        .join('\n');
    }
  } else if (p.verdict_reason) {
    badge = `<div class="badge">${p.verdict_reason}</div>`;
  }
  el.innerHTML = `<img loading="lazy" src="/thumb/${p.id}" alt="">${badge}`;
  el.addEventListener('click', (ev) => {
    if (ev.shiftKey || ev.metaKey || ev.ctrlKey) {
      openLightbox(p.id);
    } else {
      toggleSelect(p.id);
    }
  });
  return el;
}

function toggleSelect(id) {
  if (state.selected.has(id)) state.selected.delete(id);
  else state.selected.add(id);
  render();
}

function openLightbox(id) {
  $('#lightbox-img').src = `/photo/${id}`;
  $('#lightbox').hidden = false;
}
$('#lightbox').addEventListener('click', () => $('#lightbox').hidden = true);

$$('#tabs .tab').forEach(btn => btn.addEventListener('click', () => {
  $$('#tabs .tab').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  state.tab = btn.dataset.tab;
  load();
}));

$$('#reason-filters input').forEach(cb => cb.addEventListener('change', () => {
  if (cb.checked) state.reasons.add(cb.value);
  else state.reasons.delete(cb.value);
  render();
}));

$('#blur-threshold').addEventListener('input', (e) => {
  state.blurThreshold = Number(e.target.value);
  $('#blur-value').textContent = state.blurThreshold;
  if (state.tab === 'candidates') load();
});

$('#rerun-rules').addEventListener('click', async () => {
  await api('/api/rules', {
    method: 'POST',
    body: JSON.stringify({ blur_threshold: state.blurThreshold }),
  });
  load();
});

$('#btn-primary').addEventListener('click', async () => {
  if (!state.selected.size) return;
  const ids = Array.from(state.selected);
  const path = state.tab === 'trashed' ? '/api/restore' : '/api/trash';
  await api(path, { method: 'POST', body: JSON.stringify({ ids }) });
  load();
});

$('#btn-secondary').addEventListener('click', async () => {
  if (!confirm('清空回收区将永久删除这些文件,不可恢复。确定?')) return;
  await api('/api/purge', { method: 'POST', body: JSON.stringify({}) });
  load();
});

$('#btn-select-all').addEventListener('click', () => {
  const filtered = state.tab === 'candidates'
    ? state.photos.filter(p => state.reasons.has(p.verdict_reason))
    : state.photos;
  for (const p of filtered) state.selected.add(p.id);
  render();
});

$('#btn-clear').addEventListener('click', () => {
  state.selected.clear();
  render();
});

$('#label-select').addEventListener('change', (e) => {
  state.label = e.target.value || null;
  load();
});

$('#min-score').addEventListener('input', (e) => {
  state.minScore = Number(e.target.value);
  $('#min-score-value').textContent = state.minScore.toFixed(2);
  if (state.tab === 'labeled') load();
});

load();
