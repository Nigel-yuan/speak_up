const ENV_API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL?.trim() ?? "";
const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";

function normalizeBaseUrl(url: string) {
  return url.replace(/\/+$/, "");
}

function buildBrowserHostBaseUrl() {
  if (typeof window === "undefined") {
    return null;
  }

  const hostname = window.location.hostname.trim();
  if (!hostname) {
    return null;
  }

  return `http://${hostname}:8000`;
}

export function getApiBaseUrlCandidates() {
  const candidates = new Set<string>();

  if (ENV_API_BASE_URL) {
    candidates.add(normalizeBaseUrl(ENV_API_BASE_URL));
  }

  const browserHostBaseUrl = buildBrowserHostBaseUrl();
  if (browserHostBaseUrl) {
    candidates.add(normalizeBaseUrl(browserHostBaseUrl));
  }

  candidates.add(DEFAULT_API_BASE_URL);
  candidates.add("http://localhost:8000");

  return Array.from(candidates);
}

export function getApiBaseUrl() {
  return getApiBaseUrlCandidates()[0] ?? DEFAULT_API_BASE_URL;
}

export function resolveApiUrlWithBase(path: string | null | undefined, baseUrl = getApiBaseUrl()) {
  if (!path) {
    return "";
  }
  if (path.startsWith("http://") || path.startsWith("https://")) {
    return path;
  }
  return `${normalizeBaseUrl(baseUrl)}${path}`;
}
