// Fetch wrapper: JSON, CSRF header, uniform error objects.
let csrfToken = null;

export function setCsrf(token) {
  csrfToken = token;
}

export class ApiError extends Error {
  constructor(status, code) {
    super(code || `http_${status}`);
    this.status = status;
    this.code = code || `http_${status}`;
  }
}

async function request(method, url, body, opts = {}) {
  const headers = {};
  if (body !== undefined && !(body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  if (csrfToken && method !== "GET") headers["X-CSRF-Token"] = csrfToken;
  const res = await fetch(url, {
    method,
    headers,
    body: body === undefined ? undefined
      : body instanceof FormData ? body : JSON.stringify(body),
    ...opts,
  });
  if (!res.ok) {
    let code = null;
    try {
      const data = await res.json();
      code = typeof data.detail === "string" ? data.detail : null;
    } catch { /* not json */ }
    throw new ApiError(res.status, code);
  }
  const ct = res.headers.get("content-type") || "";
  return ct.includes("json") ? res.json() : res;
}

export const api = {
  get: (url) => request("GET", url),
  post: (url, body) => request("POST", url, body),
  put: (url, body) => request("PUT", url, body),
  del: (url) => request("DELETE", url),
};
