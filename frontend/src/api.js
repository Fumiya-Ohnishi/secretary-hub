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
