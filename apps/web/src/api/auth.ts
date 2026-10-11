import apiClient, {
  clearCsrfToken,
  saveCsrfToken,
} from "./client";

export type ThemePreference = "system" | "light" | "dark";
export type PreferredLanguage = "en" | "el";
export type AssistantBehavior =
  | "concise"
  | "balanced"
  | "detailed";

export interface CurrentUser {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  is_verified: boolean;
  preferred_language: PreferredLanguage;
  theme_preference: ThemePreference;
  assistant_behavior: AssistantBehavior;
  created_at: string;
  email_verified_at: string | null;
}

export interface AuthSessionResponse {
  user: CurrentUser;
  csrf_token: string;
  expires_in: number;
}

export interface RegisterRequest {
  full_name: string;
  email: string;
  password: string;
}

export interface ProfileUpdateRequest {
  full_name: string;
  preferred_language: PreferredLanguage;
  theme_preference: ThemePreference;
  assistant_behavior: AssistantBehavior;
}

export interface ActiveSession {
  id: string;
  current: boolean;
  created_at: string;
  last_used_at: string;
  expires_at: string;
  user_agent: string;
  ip_address: string;
}

export interface SecurityEvent {
  id: string;
  event_type: string;
  ip_address: string;
  user_agent: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface ActionDispatchResponse {
  message: string;
  delivery: string;
}

export async function login(credentials: {
  email: string;
  password: string;
}): Promise<AuthSessionResponse> {
  const response = await apiClient.post<AuthSessionResponse>(
    "/auth/login",
    credentials,
  );
  saveCsrfToken(response.data.csrf_token);
  return response.data;
}

export async function register(
  credentials: RegisterRequest,
): Promise<void> {
  await apiClient.post("/auth/register", credentials);
}

export async function refreshSession(): Promise<AuthSessionResponse> {
  const response = await apiClient.post<AuthSessionResponse>(
    "/auth/refresh",
  );
  saveCsrfToken(response.data.csrf_token);
  return response.data;
}

export async function logout(): Promise<void> {
  try {
    await apiClient.post("/auth/logout");
  } finally {
    clearCsrfToken();
  }
}

export async function getCurrentUser(): Promise<CurrentUser> {
  const response = await apiClient.get<CurrentUser>("/auth/me");
  return response.data;
}

export async function updateProfile(
  payload: ProfileUpdateRequest,
): Promise<CurrentUser> {
  const response = await apiClient.patch<CurrentUser>(
    "/auth/profile",
    payload,
  );
  return response.data;
}

export async function changePassword(payload: {
  current_password: string;
  new_password: string;
}): Promise<AuthSessionResponse> {
  const response = await apiClient.post<AuthSessionResponse>(
    "/auth/change-password",
    payload,
  );
  saveCsrfToken(response.data.csrf_token);
  return response.data;
}

export async function listActiveSessions(): Promise<ActiveSession[]> {
  const response = await apiClient.get<ActiveSession[]>(
    "/auth/sessions",
  );
  return response.data;
}

export async function revokeSession(sessionId: string): Promise<void> {
  await apiClient.delete(`/auth/sessions/${sessionId}`);
}

export async function logoutAllSessions(): Promise<void> {
  try {
    await apiClient.post("/auth/logout-all");
  } finally {
    clearCsrfToken();
  }
}

export async function listSecurityEvents(): Promise<SecurityEvent[]> {
  const response = await apiClient.get<SecurityEvent[]>(
    "/auth/security-events",
  );
  return response.data;
}

export async function requestPasswordReset(
  email: string,
): Promise<ActionDispatchResponse> {
  const response = await apiClient.post<ActionDispatchResponse>(
    "/auth/password-reset/request",
    { email },
  );
  return response.data;
}

export async function confirmPasswordReset(payload: {
  token: string;
  new_password: string;
}): Promise<void> {
  await apiClient.post("/auth/password-reset/confirm", payload);
  clearCsrfToken();
}

export async function requestEmailVerification(): Promise<ActionDispatchResponse> {
  const response = await apiClient.post<ActionDispatchResponse>(
    "/auth/email-verification/request",
  );
  return response.data;
}

export async function confirmEmailVerification(
  token: string,
): Promise<CurrentUser> {
  const response = await apiClient.post<CurrentUser>(
    "/auth/email-verification/confirm",
    { token },
  );
  return response.data;
}

export async function deleteAccount(payload: {
  password: string;
  confirmation: string;
}): Promise<void> {
  await apiClient.delete("/auth/account", { data: payload });
  clearCsrfToken();
}
