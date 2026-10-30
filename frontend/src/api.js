const BASE = "";

export async function getHealth() {
  const r = await fetch(`${BASE}/api/health`);
  return r.json();
}

export async function getSummary() {
  const r = await fetch(`${BASE}/api/company/summary`);
  return r.json();
}

export async function addTask(title, assignee) {
  const r = await fetch(`${BASE}/api/company/task`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ title, assignee }),
  });
  return r.json();
}

export async function sendChat(message) {
  const r = await fetch(`${BASE}/api/chat`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ message }),
  });
  return r.json();
}

export async function claudeStatus(jobId) {
  const r = await fetch(`${BASE}/api/claude/status/${jobId}`);
  return r.json();
}
