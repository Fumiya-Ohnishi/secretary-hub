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
export const decideTask = (key, decision, comment = "") =>
  call("POST", `/api/tasks/${encodeURIComponent(key)}/decision`, { decision, comment });

export const getDocs = () => call("GET", "/api/docs");
export const getDoc = (id) => call("GET", `/api/docs/${encodeURIComponent(id)}`);

export const getJobs = () => call("GET", "/api/jobs");
export const createJob = (job) => call("POST", "/api/jobs", job);

export const getBriefing = () => call("GET", "/api/briefing");
export const getContentWeeks = () => call("GET", "/api/content/weeks");
export const getContentWeek = (week) => call("GET", `/api/content/weeks/${encodeURIComponent(week)}`);
export const decidePost = (path, decision, comment = "") => call("POST", "/api/content/decision", { path, decision, comment });
export const approveWeek = (week) => call("POST", `/api/content/weeks/${encodeURIComponent(week)}/approve`);
export const recordRevenue = (r) => call("POST", "/api/metrics/revenue", r);
export const recordFollowers = (r) => call("POST", "/api/metrics/followers", r);
export const setScheduler = (s) => call("POST", "/api/scheduler", s);
export const runCheckNow = () => call("POST", "/api/scheduler/run");
export const readNotifications = (ids) => call("POST", "/api/notifications/read", { ids });
export const decideRule = (id, approve) => call("POST", `/api/rules/${encodeURIComponent(id)}/decision`, { approve });
