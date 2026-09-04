const BASE = import.meta.env.VITE_BACKEND_URL || '';
const TOKEN_KEY = 'cr2_token';

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function saveToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

export async function api(path, { method = 'GET', body } = {}) {
  const headers = { 'Content-Type': 'application/json' };
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(BASE + path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  let data = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }

  // 401 on login/register is a normal auth failure — show the server's real
  // message; 401 elsewhere means a stale token → clear it and force login.
  const isAuthRoute = path.startsWith('/auth/login') || path.startsWith('/auth/register');
  if (res.status === 401 && !isAuthRoute) {
    clearToken();
    throw new ApiError(401, 'Please log in');
  }
  if (!res.ok) {
    throw new ApiError(res.status, data?.detail || data?.error || `Request failed (${res.status})`);
  }
  return data;
}

