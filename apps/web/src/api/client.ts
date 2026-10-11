import axios, {
  type AxiosError,
  type InternalAxiosRequestConfig,
} from "axios";

import {
  SESSION_EXPIRED_EVENT,
} from "./auth-events";

const API_BASE_URL = import.meta.env.PROD
  ? "/api"
  : import.meta.env.VITE_API_BASE_URL || "/api";
export const CSRF_STORAGE_KEY = "knowledge_ai_csrf";
const CSRF_UPDATED_AT_KEY = "knowledge_ai_csrf_updated_at";

interface RetriableRequestConfig
  extends InternalAxiosRequestConfig {
  _authRetry?: boolean;
}

interface RefreshPayload {
  csrf_token: string;
}

export function saveCsrfToken(token: string): void {
  localStorage.setItem(CSRF_STORAGE_KEY, token);
  localStorage.setItem(CSRF_UPDATED_AT_KEY, String(Date.now()));
}

export function clearCsrfToken(): void {
  localStorage.removeItem(CSRF_STORAGE_KEY);
  localStorage.removeItem(CSRF_UPDATED_AT_KEY);
}

export function getCsrfToken(): string | null {
  return localStorage.getItem(CSRF_STORAGE_KEY);
}

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 180_000,
  withCredentials: true,
});

let refreshPromise: Promise<string> | null = null;

async function requestSessionRotation(): Promise<string> {
  const csrfToken = getCsrfToken();
  const response = await axios.post<RefreshPayload>(
    `${API_BASE_URL}/auth/refresh`,
    {},
    {
      withCredentials: true,
      timeout: 30_000,
      headers: csrfToken
        ? { "X-CSRF-Token": csrfToken }
        : undefined,
    },
  );
  saveCsrfToken(response.data.csrf_token);
  return response.data.csrf_token;
}

async function coordinateSessionRotation(): Promise<string> {
  const markerBefore = localStorage.getItem(CSRF_UPDATED_AT_KEY);

  const rotateInsideLock = async () => {
    const markerAfter = localStorage.getItem(CSRF_UPDATED_AT_KEY);
    const sharedToken = getCsrfToken();

    if (markerAfter !== markerBefore && sharedToken) {
      return sharedToken;
    }

    return requestSessionRotation();
  };

  if (typeof navigator !== "undefined" && navigator.locks) {
    return navigator.locks.request(
      "knowledge-ai-session-refresh",
      rotateInsideLock,
    );
  }

  return rotateInsideLock();
}

async function rotateSession(): Promise<string> {
  if (!refreshPromise) {
    refreshPromise = coordinateSessionRotation().finally(() => {
      refreshPromise = null;
    });
  }

  return refreshPromise;
}

apiClient.interceptors.request.use((config) => {
  const method = config.method?.toUpperCase() ?? "GET";
  const unsafe = !["GET", "HEAD", "OPTIONS"].includes(method);
  const csrfToken = getCsrfToken();

  if (unsafe && csrfToken) {
    config.headers["X-CSRF-Token"] = csrfToken;
  }

  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const config = error.config as RetriableRequestConfig | undefined;
    const status = error.response?.status;
    const requestUrl = String(config?.url ?? "");
    const isSessionEndpoint = [
      "/auth/login",
      "/auth/register",
      "/auth/refresh",
      "/auth/logout",
      "/auth/password-reset/request",
      "/auth/password-reset/confirm",
      "/auth/email-verification/confirm",
    ].some((path) => requestUrl.includes(path));

    if (
      status === 401 &&
      config &&
      !config._authRetry &&
      !isSessionEndpoint
    ) {
      config._authRetry = true;

      try {
        await rotateSession();
        return apiClient(config);
      } catch {
        clearCsrfToken();
        sessionStorage.setItem(
          "auth_notice",
          "Your session has expired. Please sign in again.",
        );
        window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
      }
    }

    return Promise.reject(error);
  },
);

export default apiClient;
