// A plain (non-React) module so the imperative fetch client (api/client.ts) and the React
// AuthContext can both read/write the token without one importing the other's hook.
const STORAGE_KEY = "bia_token";

export function getToken(): string | null {
  return localStorage.getItem(STORAGE_KEY);
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(STORAGE_KEY, token);
  else localStorage.removeItem(STORAGE_KEY);
}
