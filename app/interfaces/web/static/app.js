const SHOW_COGNITION = new URLSearchParams(window.location.search).get('debug') === '1';

const state = {
  sessionId: localStorage.getItem('shury.session') || crypto.randomUUID(),
  sessionToken: localStorage.getItem('shury.session.token') || '',
  taskId: null,
  pollTimer: null,
  pollDelay: 450,
  pollFailures: 0,
  shownTaskIds: new Set(),
};
if (!state.sessionToken) {
  state.sessionId = crypto.randomUUID();
}
localStorage.setItem('shury.session', state.sessionId);
if (state.sessionToken) localStorage.setItem('shury.session.token', state.sessionToken);

const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}

function humanizeAgentText(value) {
  if (value == null) return '';
  if (typeof value === 'object') {
    if (typeof value.final_message === 'string' && value.final_message.trim()) return humanizeAgentText(value.final_message);
    if (value.state) {
      const nested = humanizeAgentText(value.state);
      if (nested) return nested;
    }
    if (typeof value.message === 'string' && value.message.trim()) return value.message.trim();
    return '';
  }
  const text = String(value).trim();
  if (!text) return '';
  if ((text.startsWith('{') && text.endsWith('}')) || (text.startsWith('[') && text.endsWith(']'))) {
    try {
      const parsed = JSON.parse(text);
      if (parsed && typeof parsed === 'object') {
        const human = humanizeAgentText(parsed);
        if (human) return human;
      }
    } catch (_) {
      // Keep legitimate plain text untouched.
    }
  }
  if (/^(?:\{.*"task_id"\s*:|\[?\{.*"task_id"\s*:)/s.test(text)) {
    return 'انتهت العملية، لكن لم يصل رد مفهوم من الخادم.';
  }
  return text;
}

function addMessage(role, text, meta = '', persist = false, cognitive = null) {
  const safeText = String(text ?? '').trim();
  if (!safeText) return;
  const wrap = document.createElement('div');
  wrap.className = `message ${role}`;
  const avatar = document.createElement('div');
  avatar.className = 'avatar';
  avatar.textContent = role === 'user' ? 'You' : 'س';
  const body = document.createElement('div');
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = safeText;
  body.appendChild(bubble);
  if (meta) {
    const m = document.createElement('div');
    m.className = 'meta';
    m.textContent = meta;
    body.appendChild(m);
  }
  if (role === 'agent' && cognitive && SHOW_COGNITION) body.appendChild(renderCognition(cognitive));
  wrap.appendChild(avatar);
  wrap.appendChild(body);
  $('messages').appendChild(wrap);
  $('messages').scrollTop = $('messages').scrollHeight;
  return wrap;
}

async function fetchJson(url, options = {}, timeoutMs = 6000) {
  const controller = new AbortController();
  const headers = {...(options.headers || {})};
  if (state.sessionToken) headers['X-Session-Token'] = state.sessionToken;
  const timer = setTimeout(() => controller.abort('timeout'), timeoutMs);
  try {
    const response = await fetch(url, {...options, headers, signal: controller.signal, cache: 'no-store'});
    const text = await response.text();
    let data = {};
    try { data = text ? JSON.parse(text) : {}; } catch { data = {error: text || 'Invalid server response'}; }
    if (!response.ok) {
      const error = new Error(data.error || `HTTP ${response.status}`);
      error.status = response.status;
      throw error;
    }
    return data;
  } finally {
    clearTimeout(timer);
  }
}

function setBusy(busy) {
  $('input').disabled = Boolean(busy);
  $('send').disabled = Boolean(busy);
  $('send').textContent = busy ? '…' : '➜';
}

function setConnectionHint(text) {
  const hint = document.querySelector('.composer-hint');
  if (hint) hint.textContent = text;
}


function renderCognition(summary) {
  const panel = document.createElement('details');
  panel.className = 'cognition';
  panel.open = true;

  const header = document.createElement('div');
  header.className = 'cognition-header';
  const title = document.createElement('div');
  title.className = 'cognition-title';
  title.textContent = 'Cognitive evidence';
  const mode = document.createElement('span');
  mode.className = 'cognition-mode';
  mode.textContent = summary.planning_mode || 'reasoning';
  header.append(title, mode);
  panel.appendChild(header);

  const process = document.createElement('div');
  process.className = 'cognition-process';
  for (const stage of (summary.stages || [])) {
    const chip = document.createElement('span');
    chip.className = `cognition-stage${stage.complete ? ' is-complete' : ''}`;
    chip.textContent = stage.name;
    process.appendChild(chip);
  }
  if (process.children.length) panel.appendChild(process);

  const grid = document.createElement('div');
  grid.className = 'cognition-grid';
  const add = (label, value, tone = '') => {
    if (value == null || value === '') return;
    const item = document.createElement('div');
    item.className = 'cognition-item';
    if (tone) item.dataset.tone = tone;
    const l = document.createElement('span');
    l.textContent = label;
    const v = document.createElement('strong');
    v.textContent = String(value);
    item.append(l, v);
    grid.appendChild(item);
  };

  add('Decision', summary.decision || '—', summary.decision === 'clarify' ? 'warn' : 'good');
  if (summary.decision_confidence != null) add('Confidence', `${Math.round(summary.decision_confidence * 100)}%`);
  add('Goal', summary.goal || '—');
  add('Planning', summary.planning_mode || '—');
  add('Evidence', summary.evidence_count ?? 0);
  if (summary.model_uncertainty != null) add('Model uncertainty', `${Math.round(summary.model_uncertainty * 100)}%`, summary.model_uncertainty >= 0.55 ? 'warn' : '');
  if (summary.uncertainty_reasons?.length) add('Open uncertainty', summary.uncertainty_reasons.join(' · '), 'warn');
  if (summary.plan?.length) add('Plan', summary.plan.join(' → '), 'good');

  if (summary.exploration) {
    const e = summary.exploration;
    add('Exploration', e.tool ? `${e.strategy || e.mode} · ${e.tool}` : (e.strategy || e.mode));
    add('Info gain', Number(e.information_gain || 0).toFixed(3));
    add('Info value', Number(e.information_value || 0).toFixed(3));
    add('Expected failure cost', Number(e.expected_failure_cost || 0).toFixed(3));
    add('UCB', Number(e.ucb_bonus || 0).toFixed(3));
  }
  if (summary.prediction_error) {
    add('Prediction error', Number(summary.prediction_error.mean_error || 0).toFixed(3), 'warn');
    add('Surprise', Number(summary.prediction_error.surprise || 0).toFixed(3), 'warn');
  }
  if (summary.learning) {
    const l = summary.learning;
    const updates = [];
    if (l.transitions) updates.push(`model +${l.transitions}`);
    if (l.state_updates) updates.push(`V +${l.state_updates}`);
    if (l.action_updates) updates.push(`Q +${l.action_updates}`);
    if (l.replay_indexed) updates.push(`replay +${l.replay_indexed}`);
    if (l.prediction_scored) updates.push(`error +${l.prediction_scored}`);
    if (updates.length) add('Learning updates', updates.join(' · '), 'good');
  }
  if (summary.decision_rationale) add('Decision basis', summary.decision_rationale);
  panel.appendChild(grid);

  const alternatives = (summary.alternatives || []).filter(item => item && item.tool).slice(0, 6);
  if (alternatives.length) {
    const section = document.createElement('div');
    section.className = 'cognition-section';
    const sectionTitle = document.createElement('div');
    sectionTitle.className = 'cognition-section-title';
    sectionTitle.textContent = 'Candidate actions';
    section.appendChild(sectionTitle);
    for (const item of alternatives) {
      const row = document.createElement('div');
      row.className = 'cognition-candidate';
      const name = document.createElement('span');
      name.textContent = item.tool;
      const metrics = [];
      if (item.score != null) metrics.push(`score ${Number(item.score).toFixed(2)}`);
      if (item.evidence_count != null) metrics.push(`${item.evidence_count} obs`);
      if (item.information_gain != null) metrics.push(`gain ${Number(item.information_gain).toFixed(2)}`);
      if (item.information_value != null) metrics.push(`VOI ${Number(item.information_value).toFixed(2)}`);
      if (item.expected_failure_cost != null) metrics.push(`risk-cost ${Number(item.expected_failure_cost).toFixed(2)}`);
      const meta = document.createElement('small');
      meta.textContent = metrics.join(' · ');
      row.append(name, meta);
      section.appendChild(row);
    }
    panel.appendChild(section);
  }

  const evidence = (summary.evidence || []).filter(item => item && (item.content || item.source)).slice(0, 4);
  if (evidence.length) {
    const section = document.createElement('div');
    section.className = 'cognition-section';
    const sectionTitle = document.createElement('div');
    sectionTitle.className = 'cognition-section-title';
    sectionTitle.textContent = 'Evidence actually used';
    section.appendChild(sectionTitle);
    for (const item of evidence) {
      const row = document.createElement('div');
      row.className = 'cognition-evidence';
      const source = document.createElement('strong');
      source.textContent = item.source || item.kind || 'evidence';
      const content = document.createElement('span');
      content.textContent = item.content || '';
      row.append(source, content);
      section.appendChild(row);
    }
    panel.appendChild(section);
  }

  return panel;
}

async function loadIdentity() {
  const identity = await fetchJson('/api/identity', {}, 5000);
  $('agent-name').textContent = identity.name;
  $('agent-role').textContent = identity.role;
  $('agent-mission').textContent = identity.mission;
  $('agent-background').innerHTML = (identity.background || []).map(x => `<div>${escapeHtml(x)}</div>`).join('');
  $('agent-principles').innerHTML = (identity.principles || []).map(x => `<div>${escapeHtml(x)}</div>`).join('');
  const health = await fetchJson('/api/health', {}, 5000);
  $('brain-status').textContent = health.brain?.learning ? 'Learning + exploration' : 'Deterministic';
  const mode = $('brain-mode');
  if (mode) mode.textContent = health.brain?.learning ? 'Learning + exploration' : 'Deterministic';
}

function clearPolling() {
  if (state.pollTimer) clearTimeout(state.pollTimer);
  state.pollTimer = null;
}

function schedulePoll(delay = state.pollDelay) {
  clearPolling();
  state.pollTimer = setTimeout(pollTask, delay);
}

function taskPollUrl(taskId) {
  const params = new URLSearchParams({id: taskId});
  if (SHOW_COGNITION) params.set('debug', '1');
  return `/api/tasks?${params.toString()}`;
}

function sessionPollUrl() {
  const params = new URLSearchParams({session_id: state.sessionId});
  if (SHOW_COGNITION) params.set('debug', '1');
  return `/api/session?${params.toString()}`;
}

function renderHistory(episodes) {
  $('messages').innerHTML = '';
  const ordered = [...(episodes || [])].reverse();
  for (const episode of ordered) {
    if (episode.user_text) addMessage('user', episode.user_text, '', false);
    const assistantText = humanizeAgentText(episode.assistant_text);
    if (assistantText) addMessage('agent', assistantText, episode.outcome || '', false);
  }
}

async function recoverSession() {
  try {
    const data = await fetchJson(sessionPollUrl(), {}, 7000);
    renderHistory(data.episodes);
    const persistedTaskId = localStorage.getItem('shury.task');
  const latest = data.latest_task;
  if (persistedTaskId && latest && latest.task_id === persistedTaskId) state.taskId = persistedTaskId;
    if (latest && ['queued', 'running', 'waiting_approval'].includes(latest.status)) {
      state.taskId = latest.task_id;
      localStorage.setItem('shury.task', state.taskId);
      state.pollFailures = 0;
      state.pollDelay = 450;
      setBusy(true);
      addMessage('agent', 'رجعت للمحادثة. عندي عملية كانت لسه قيد التنفيذ، هكمل متابعتها من هنا.');
      schedulePoll(120);
      return true;
    }
    if (!$('messages').children.length) {
      addMessage('agent', 'أهلًا بك. أنا شوري — قولّي نبدأ بإيه؟');
    }
  } catch (error) {
    if (!$('messages').children.length) {
      addMessage('agent', 'بدأت محليًا، لكن لم أستطع تحميل سجل المحادثة الآن.');
    }
  }
  return false;
}

async function submitMessage(message) {
  addMessage('user', message);
  $('input').value = '';
  setBusy(true);
  setConnectionHint('شوري بيشتغل على طلبك وبيتأكد من النتيجة قبل ما يرجع لك بالرد.');
  try {
    const data = await fetchJson('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message, session_id: state.sessionId}),
    }, 8000);
    state.taskId = data.task_id;
    localStorage.setItem('shury.task', state.taskId);
    state.pollFailures = 0;
    state.pollDelay = 450;
    schedulePoll();
  } catch (error) {
    state.taskId = null;
    setBusy(false);
    setConnectionHint('يمكنك المحاولة مرة أخرى.');
    addMessage('agent', error.name === 'AbortError'
      ? 'الطلب لم يصل للخادم في الوقت المتوقع. الواجهة رجعت للعمل ويمكنك المحاولة مرة أخرى.'
      : `تعذر إرسال الطلب: ${error.message}`);
  }
}

async function recoverActiveTask() {
  try {
    const data = await fetchJson(sessionPollUrl(), {}, 6500);
    const persistedTaskId = localStorage.getItem('shury.task');
  const latest = data.latest_task;
  if (persistedTaskId && latest && latest.task_id === persistedTaskId) state.taskId = persistedTaskId;
    if (latest && latest.task_id === state.taskId) {
      state.pollFailures = 0;
      state.pollDelay = 450;
      if (['queued', 'running', 'waiting_approval'].includes(latest.status)) {
        setBusy(true);
        setConnectionHint('استعدت الاتصال بالعملية؛ SHURY مكمل من نفس الحالة.');
        schedulePoll(100);
        return true;
      }
      handleFinishedTask(latest);
      return true;
    }
  } catch (error) {
    console.warn('SHURY task recovery failed', error);
  }
  return false;
}

function handleFinishedTask(task) {
  const st = task.state;
  if (task.error) {
    addMessage('agent', task.error, task.status);
  } else if (st?.final_message) {
    const message = humanizeAgentText(st.final_message);
    addMessage('agent', message || 'وصلت نتيجة العملية لكن بدون رد نصي واضح.', task.status === 'completed' ? '' : task.status, false, st.cognitive?.summary || null);
  } else {
    addMessage('agent', humanizeAgentText(task) || `انتهت العملية بحالة: ${task.status}`);
  }
  $('approval').classList.add('hidden');
  state.taskId = null;
  localStorage.removeItem('shury.task');
  setBusy(false);
  setConnectionHint('SHURY رجع للعمل وجاهز للطلب التالي.');
}

async function pollTask() {
  clearPolling();
  if (!state.taskId) return;
  try {
    const task = await fetchJson(taskPollUrl(state.taskId), {}, 5000);
    state.pollFailures = 0;
    state.pollDelay = Math.min(1800, Math.round(state.pollDelay * 1.25));

    if (task.approval) {
      $('approval').classList.remove('hidden');
      $('approval-text').textContent = `${task.approval.tool} — ${JSON.stringify(task.approval.args)}`;
    } else {
      $('approval').classList.add('hidden');
    }

    if (['queued', 'running', 'waiting_approval'].includes(task.status)) {
      setBusy(true);
      setConnectionHint(task.status === 'waiting_approval'
        ? 'SHURY مستني موافقتك على العملية التالية.'
        : 'SHURY يعمل على الطلب…');
      schedulePoll();
      return;
    }

    handleFinishedTask(task);
  } catch (error) {
    state.pollFailures += 1;
    // Recover the active task from the session store before releasing the task id.
    // This covers browser/network interruption without forcing the user to refresh.
    if (state.pollFailures === 2 || state.pollFailures === 4) {
      if (await recoverActiveTask()) return;
    }
    if (state.pollFailures >= 6) {
      const taskId = state.taskId;
      // Keep the turn active and keep recovering it automatically. Do not re-enable the
      // composer while an unknown server-side task may still be running; that would let
      // a user start duplicate work and make the conversation inconsistent.
      setBusy(true);
      $('approval').classList.add('hidden');
      setConnectionHint('فقدت الاتصال مؤقتًا؛ SHURY بيحاول استرجاع نفس العملية تلقائيًا، ومش محتاج تعيد فتح الصفحة.');
      if (state.pollFailures === 6) {
        addMessage('agent', `الاتصال بالعملية ${taskId.slice(0, 8)}… انقطع مؤقتًا. هستمر في الاسترجاع تلقائيًا.`);
      }
      // Keep taskId so visibilitychange/reconnect can continue polling.
      schedulePoll(4000);
      return;
    }
    state.pollDelay = Math.min(2500, Math.round(state.pollDelay * 1.7));
    schedulePoll();
  }
}

async function decideApproval(approved) {
  if (!state.taskId) return;
  try {
    await fetchJson('/api/approval', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({task_id:state.taskId, approved}),
    }, 5000);
    schedulePoll(100);
  } catch (error) {
    addMessage('agent', `تعذر تسجيل الموافقة: ${error.message}`);
  }
}

$('composer').addEventListener('submit', (e) => {
  e.preventDefault();
  const value = $('input').value.trim();
  if (value && !state.taskId) submitMessage(value);
});

$('input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    $('composer').requestSubmit();
  }
});

$('approve').addEventListener('click', () => decideApproval(true));
$('deny').addEventListener('click', () => decideApproval(false));
$('new-chat').addEventListener('click', () => {
  clearPolling();
  state.taskId = null;
  localStorage.removeItem('shury.task');
  state.pollFailures = 0;
  state.pollDelay = 450;
  state.sessionId = crypto.randomUUID();
  if (!state.sessionToken) {
  state.sessionId = crypto.randomUUID();
}
localStorage.setItem('shury.session', state.sessionId);
if (state.sessionToken) localStorage.setItem('shury.session.token', state.sessionToken);
  $('approval').classList.add('hidden');
  $('messages').innerHTML = '';
  setBusy(false);
  setConnectionHint('SHURY يقدر يفكر ويبحث ويتذكر ويحلل وينفذ العمليات المصرح بها.');
  addMessage('agent', 'بدأنا محادثة جديدة. قولّي نشتغل على إيه؟');
});

window.addEventListener('error', (event) => {
  console.error('SHURY UI error', event.error || event.message);
  // A frontend exception must not strand the composer in disabled state.
  if (!state.taskId) setBusy(false);
});
window.addEventListener('unhandledrejection', (event) => {
  console.error('SHURY UI promise rejection', event.reason);
  if (!state.taskId) setBusy(false);
});

document.addEventListener('visibilitychange', () => {
  if (!document.hidden && state.taskId) schedulePoll(100);
});

(async () => {
  try { await loadIdentity(); } catch (error) { console.error(error); }
  await recoverSession();
})();
