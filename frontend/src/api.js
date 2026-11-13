async function call(method, path, body) {
  const r = await fetch(path, {
    method,
    headers: body ? { "content-type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `通信エラー(${r.status})`);
  return data;
}

export const getHealth = () => call("GET", "/api/health");
export const getSummary = () => call("GET", "/api/company/summary");
export const sendChat = (message, history) => call("POST", "/api/chat", { message, history });

export const createTask = (task) => call("POST", "/api/tasks", task);
export const patchTask = (key, patch) => call("PATCH", `/api/tasks/${encodeURIComponent(key)}`, patch);
export const resumeTask = (key) => call("POST", `/api/tasks/${encodeURIComponent(key)}/resume`);
export const decideTask = (key, decision, comment = "") =>
  call("POST", `/api/tasks/${encodeURIComponent(key)}/decision`, { decision, comment });

export const getDocs = () => call("GET", "/api/docs");
export const getWorklog = (days = 60) => call("GET", `/api/worklog?days=${days}`);
export const getDocTree = () => call("GET", "/api/docs/tree");
export const getDoc = (id) => call("GET", `/api/docs/${encodeURIComponent(id)}`);

export const getJobs = () => call("GET", "/api/jobs");
export const createJob = (job) => call("POST", "/api/jobs", job);

export const getBriefing = () => call("GET", "/api/briefing");
export const getContentWeeks = () => call("GET", "/api/content/weeks");
export const getContentWeek = (week) => call("GET", `/api/content/weeks/${encodeURIComponent(week)}`);
export const decidePost = (path, decision, comment = "") => call("POST", "/api/content/decision", { path, decision, comment });
export const approveWeek = (week, account) => call("POST", `/api/content/weeks/${encodeURIComponent(week)}/approve${account ? `?account=${encodeURIComponent(account)}` : ""}`);
export const recordRevenue = (r) => call("POST", "/api/metrics/revenue", r);
export const recordFollowers = (r) => call("POST", "/api/metrics/followers", r);
export const setScheduler = (s) => call("POST", "/api/scheduler", s);
export const runCheckNow = () => call("POST", "/api/scheduler/run");
export const runNewsFlash = () => call("POST", "/api/news/flash");
export const readNotifications = (ids) => call("POST", "/api/notifications/read", { ids });
export const decideRule = (id, approve) => call("POST", `/api/rules/${encodeURIComponent(id)}/decision`, { approve });

/** 返事を少しずつ受け取る。onEvent({t:"text",v}) / ({t:"actions",v}) / ({t:"done",reply,mood,actions}) */
export async function chatStream(message, history, onEvent) {
  const r = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ message, history }),
  });
  if (!r.ok || !r.body) throw new Error(`通信エラー(${r.status})`);
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "", done = null;
  for (;;) {
    const { value, done: end } = await reader.read();
    if (end) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, i).trim();
      buf = buf.slice(i + 1);
      if (!line) continue;
      const ev = JSON.parse(line);
      if (ev.t === "done") done = ev;
      onEvent(ev);
    }
  }
  if (!done) throw new Error("返事が途中で切れました");
  return done;
}

export const getToPost = () => call("GET", "/api/content/to_post");
export const getAllPosts = () => call("GET", "/api/content/posts");
export const schedulePost = (path, date) => call("POST", "/api/content/schedule", { path, date });
export const getOrg = () => call("GET", "/api/org");
export const search = (q) => call("GET", `/api/search?q=${encodeURIComponent(q)}`);
export const getDiagnostics = () => call("GET", "/api/diagnostics");
export const getAccounts = (account = "main") => call("GET", `/api/accounts?account=${encodeURIComponent(account)}`);
export const getAccount = (p, account = "main") => call("GET", `/api/accounts/${encodeURIComponent(p)}?account=${encodeURIComponent(account)}`);
export const addInsight = (p, values, date, perPost = false, account = "main") => call("POST", `/api/accounts/${encodeURIComponent(p)}/insights`, { values, date, per_post: perPost, account });
export const getPostResults = (p, id, account = "main") => call("GET", `/api/accounts/${encodeURIComponent(p)}/results?id=${encodeURIComponent(id)}&account=${encodeURIComponent(account)}`);
export const markCrossposted = (p, path, undo = false) => call("POST", `/api/accounts/${encodeURIComponent(p)}/crossposted`, { path, undo });
export const addImprovement = (p, text, account = "main") => call("POST", `/api/accounts/${encodeURIComponent(p)}/improvements`, { text, account });
// 請け負いの提案(ランサーズ・ココナラ。2026-11-12)
export const registerAccount = (platform, url, account = "main") => call("POST", "/api/accounts", { platform, url, account });
export const addAccountSet = (label, note = "") => call("POST", "/api/account_sets", { label, note });
export const getStamps = (kind = "") => call("GET", `/api/stamps${kind ? `?kind=${kind}` : ""}`);
export const decideStamp = (id, action, comment = "", url = "") => call("POST", `/api/stamps/${encodeURIComponent(id)}/decision`, { action, comment, url });
export const syncStats = (only = "") => call("POST", `/api/stats/sync${only ? `?only=${encodeURIComponent(only)}` : ""}`);
export const getProposals = (service) => call("GET", `/api/proposals${service ? `?service=${encodeURIComponent(service)}` : ""}`);
export const addProposal = (p) => call("POST", "/api/proposals", p);
export const patchProposal = (id, p) => call("PATCH", `/api/proposals/${encodeURIComponent(id)}`, p);
export const proposalRevenue = (id, amount, date) => call("POST", `/api/proposals/${encodeURIComponent(id)}/revenue`, { amount, date });
export const getKnowledge = () => call("GET", "/api/knowledge");
export const searchKnowledge = (q) => call("GET", `/api/knowledge/search?q=${encodeURIComponent(q)}`);
export const addPref = (p) => call("POST", "/api/knowledge/prefs", p);
export const decidePref = (id, approve, revised = "") => call("POST", `/api/knowledge/prefs/${encodeURIComponent(id)}`, { approve, revised });
export const getMeetings = () => call("GET", "/api/meetings");
export const startMeeting = (kind, topic = "", departments = null) => call("POST", "/api/meetings", { kind, topic, departments });

// 参考動画の分析(動画は本文そのままで送る)
export const listVideoRefs = () => call("GET", "/api/video_refs");
export async function uploadVideoRef(file, name, note) {
  const q = new URLSearchParams({ name: name || "", note: note || "" });
  const r = await fetch(`/api/video_refs?${q}`, { method: "POST", headers: { "x-filename": encodeURIComponent(file.name) }, body: file });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `通信エラー(${r.status})`);
  return data;
}

// Muse の答え(社長が Instagram の Muse に聞いた答えを貼る)
export const getMuse = () => call("GET", "/api/muse");
export const saveMuse = (text, kind) => call("POST", "/api/muse", { text, kind });
