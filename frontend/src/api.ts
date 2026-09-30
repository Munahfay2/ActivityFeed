let token = sessionStorage.getItem("t") || "";
export const setToken = (t: string) => { token = t; t ? sessionStorage.setItem("t", t) : sessionStorage.removeItem("t"); };
export const hasToken = () => !!token;
export async function api(path: string, body?: any, method?: string) {
  const r = await fetch("/api" + path, { method: method || (body ? "POST" : "GET"),
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: "Bearer " + token } : {}) },
    body: body ? JSON.stringify(body) : undefined });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "Please check the form and try again.");
  return d;
}
