import {
  BadgeCheck,
  BookOpen,
  Bot,
  CalendarDays,
  CheckCircle2,
  FileText,
  Globe2,
  KeyRound,
  Laptop2,
  LogOut,
  Mail,
  Monitor,
  Moon,
  RefreshCw,
  Send,
  ShieldCheck,
  Sun,
  Trash2,
  UserRound,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from "react";
import {
  changePassword,
  deleteAccount,
  getCurrentUser,
  listActiveSessions,
  listSecurityEvents,
  logoutAllSessions,
  requestEmailVerification,
  revokeSession,
  updateProfile,
  type ActiveSession,
  type AssistantBehavior,
  type CurrentUser,
  type PreferredLanguage,
  type SecurityEvent,
} from "../api/auth";
import {
  listDocuments,
} from "../api/documents";
import {
  getApiErrorMessage,
} from "../api/errors";
import {
  withApiRetry,
} from "../api/retry";
import {
  listWikiPages,
} from "../api/wiki";
import ConfirmDialog from "../components/ConfirmDialog";
import FeedbackBanner from "../components/FeedbackBanner";
import {
  useAuth,
} from "../context/AuthContext";
import {
  useTheme,
  type ThemePreference,
} from "../context/ThemeContext";

interface ProfileStats {
  documents: number;
  wikiPages: number;
}

const themeOptions: Array<{
  value: ThemePreference;
  label: string;
  description: string;
  icon: typeof Sun;
}> = [
  {
    value: "light",
    label: "Light",
    description: "Bright, calm workspace.",
    icon: Sun,
  },
  {
    value: "dark",
    label: "Dark",
    description: "Reduced glare in low light.",
    icon: Moon,
  },
  {
    value: "system",
    label: "System",
    description: "Follow your device setting.",
    icon: Monitor,
  },
];

const eventLabels: Record<string, string> = {
  LOGIN_SUCCESS: "Signed in",
  LOGIN_FAILURE: "Failed sign-in attempt",
  LOGIN_BLOCKED: "Sign-in temporarily blocked",
  TOKEN_REFRESHED: "Session renewed",
  LOGOUT: "Signed out",
  LOGOUT_ALL: "Signed out everywhere",
  SESSION_REVOKED: "Session revoked",
  PROFILE_UPDATED: "Profile updated",
  PASSWORD_CHANGED: "Password changed",
  PASSWORD_RESET_REQUESTED: "Password reset requested",
  PASSWORD_RESET_COMPLETED: "Password reset completed",
  EMAIL_VERIFICATION_REQUESTED: "Email verification requested",
  EMAIL_VERIFIED: "Email verified",
};

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function sessionName(userAgent: string): string {
  if (/iphone|ipad/i.test(userAgent)) {
    return "Apple mobile device";
  }
  if (/android/i.test(userAgent)) {
    return "Android device";
  }
  if (/macintosh|mac os/i.test(userAgent)) {
    return "Mac browser";
  }
  if (/windows/i.test(userAgent)) {
    return "Windows browser";
  }
  return "Browser session";
}

export default function ProfilePage() {
  const {
    user: contextUser,
    setUser,
    signOut,
  } = useAuth();
  const {
    preference,
    setPreference,
  } = useTheme();

  const [user, setLocalUser] = useState<CurrentUser | null>(
    contextUser,
  );
  const [stats, setStats] = useState<ProfileStats>({
    documents: 0,
    wikiPages: 0,
  });
  const [sessions, setSessions] = useState<ActiveSession[]>([]);
  const [events, setEvents] = useState<SecurityEvent[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRetrying, setIsRetrying] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [isSavingProfile, setIsSavingProfile] = useState(false);
  const [isChangingPassword, setIsChangingPassword] = useState(false);
  const [busySessionId, setBusySessionId] = useState("");
  const [isSendingVerification, setIsSendingVerification] =
    useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);

  const [fullName, setFullName] = useState(contextUser?.full_name ?? "");
  const [language, setLanguage] = useState<PreferredLanguage>(
    contextUser?.preferred_language ?? "en",
  );
  const [assistantBehavior, setAssistantBehavior] =
    useState<AssistantBehavior>(
      contextUser?.assistant_behavior ?? "balanced",
    );
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [deletePassword, setDeletePassword] = useState("");
  const [deleteConfirmation, setDeleteConfirmation] = useState("");

  const currentSession = useMemo(
    () => sessions.find((session) => session.current) ?? null,
    [sessions],
  );

  const applyUser = useCallback(
    (nextUser: CurrentUser) => {
      setLocalUser(nextUser);
      setUser(nextUser);
      setFullName(nextUser.full_name);
      setLanguage(nextUser.preferred_language);
      setAssistantBehavior(nextUser.assistant_behavior);
      setPreference(nextUser.theme_preference);
    },
    [setPreference, setUser],
  );

  const loadProfile = useCallback(async () => {
    setError("");
    setIsLoading(true);
    setIsRetrying(false);

    try {
      const [
        currentUser,
        documents,
        pages,
        activeSessions,
        securityEvents,
      ] = await withApiRetry(
        () =>
          Promise.all([
            getCurrentUser(),
            listDocuments(),
            listWikiPages(),
            listActiveSessions(),
            listSecurityEvents(),
          ]),
        {
          retries: 2,
          onRetry: () => setIsRetrying(true),
        },
      );

      applyUser(currentUser);
      setStats({
        documents: documents.length,
        wikiPages: pages.length,
      });
      setSessions(activeSessions);
      setEvents(securityEvents);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setIsLoading(false);
      setIsRetrying(false);
    }
  }, [applyUser]);

  useEffect(() => {
    void loadProfile();
  }, [loadProfile]);

  function resetFeedback() {
    setError("");
    setNotice("");
  }

  async function handleProfileSave(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault();
    resetFeedback();
    setIsSavingProfile(true);

    try {
      const updated = await updateProfile({
        full_name: fullName,
        preferred_language: language,
        theme_preference: preference,
        assistant_behavior: assistantBehavior,
      });
      applyUser(updated);
      setNotice("Profile and Assistant preferences saved.");
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setIsSavingProfile(false);
    }
  }

  async function handlePasswordChange(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault();
    resetFeedback();

    if (newPassword !== confirmPassword) {
      setError("The two new passwords do not match.");
      return;
    }

    setIsChangingPassword(true);
    try {
      const result = await changePassword({
        current_password: currentPassword,
        new_password: newPassword,
      });
      applyUser(result.user);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setNotice(
        "Password changed. Other active sessions were signed out.",
      );
      const activeSessions = await listActiveSessions();
      setSessions(activeSessions);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setIsChangingPassword(false);
    }
  }

  async function handleVerificationRequest() {
    resetFeedback();
    setIsSendingVerification(true);

    try {
      const result = await requestEmailVerification();
      setNotice(result.message);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setIsSendingVerification(false);
    }
  }

  async function handleRevokeSession(sessionId: string) {
    resetFeedback();
    setBusySessionId(sessionId);
    try {
      await revokeSession(sessionId);
      setSessions((current) =>
        current.filter((session) => session.id !== sessionId),
      );
      setNotice("Session revoked.");
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setBusySessionId("");
    }
  }

  async function handleLogoutAll() {
    resetFeedback();
    try {
      await logoutAllSessions();
      setUser(null);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    }
  }

  async function handleDeleteAccount() {
    resetFeedback();
    setIsDeleting(true);
    try {
      await deleteAccount({
        password: deletePassword,
        confirmation: deleteConfirmation,
      });
      setUser(null);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
      setIsDeleteDialogOpen(false);
    } finally {
      setIsDeleting(false);
    }
  }

  return (
    <section className="page-container profile-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">Account & preferences</p>
          <h1>My Profile</h1>
          <p>
            Manage your identity, Assistant behavior and account
            security from one place.
          </p>
        </div>
      </header>

      {isRetrying && (
        <FeedbackBanner
          kind="retrying"
          message="The server is waking up. Retrying…"
        />
      )}
      {notice && !isRetrying && (
        <FeedbackBanner kind="success" message={notice} />
      )}
      {error && !isRetrying && (
        <FeedbackBanner
          kind="error"
          message={error}
          onRetry={() => void loadProfile()}
        />
      )}

      {isLoading && !isRetrying ? (
        <div className="skeleton-stack" aria-label="Loading profile">
          <div className="skeleton-card" />
          <div className="skeleton-card" />
          <div className="skeleton-card" />
        </div>
      ) : user ? (
        <div className="profile-grid profile-grid-expanded">
          <section className="surface-card profile-summary-card">
            <div className="profile-avatar">
              <UserRound size={30} />
            </div>

            <div>
              <p className="eyebrow">Signed in as</p>
              <h2>{user.full_name}</h2>
              <p className="profile-email">
                <Mail size={16} />
                {user.email}
              </p>
            </div>

            <div className="profile-details">
              <span>
                <CheckCircle2 size={17} />
                {user.is_active ? "Active account" : "Inactive account"}
              </span>
              <span>
                <CalendarDays size={17} />
                Joined {formatDate(user.created_at)}
              </span>
              <span>
                <BadgeCheck size={17} />
                {user.is_verified
                  ? "Verified email"
                  : "Email verification pending"}
              </span>
            </div>
          </section>

          <section className="surface-card profile-stats-card">
            <div>
              <FileText size={21} />
              <strong>{stats.documents}</strong>
              <span>Documents</span>
            </div>
            <div>
              <BookOpen size={21} />
              <strong>{stats.wikiPages}</strong>
              <span>Wiki pages</span>
            </div>
          </section>

          <form
            className="surface-card profile-section-card"
            onSubmit={handleProfileSave}
          >
            <div className="section-heading-row">
              <div>
                <p className="eyebrow">Personal information</p>
                <h2>Name and preferences</h2>
                <p>
                  These settings personalize the workspace and the
                  Assistant response style.
                </p>
              </div>
              <UserRound size={22} />
            </div>

            <div className="profile-form-grid">
              <label>
                Full name
                <input
                  type="text"
                  value={fullName}
                  onChange={(event) => setFullName(event.target.value)}
                  minLength={2}
                  required
                />
              </label>

              <label>
                Preferred language
                <div className="select-wrapper">
                  <Globe2 size={17} />
                  <select
                    value={language}
                    onChange={(event) =>
                      setLanguage(
                        event.target.value as PreferredLanguage,
                      )
                    }
                  >
                    <option value="en">English</option>
                    <option value="el">Greek</option>
                  </select>
                </div>
              </label>

              <label>
                Default Assistant behavior
                <div className="select-wrapper">
                  <Bot size={17} />
                  <select
                    value={assistantBehavior}
                    onChange={(event) =>
                      setAssistantBehavior(
                        event.target.value as AssistantBehavior,
                      )
                    }
                  >
                    <option value="concise">Concise</option>
                    <option value="balanced">Balanced</option>
                    <option value="detailed">Detailed</option>
                  </select>
                </div>
              </label>
            </div>

            <div className="theme-option-grid compact-theme-grid">
              {themeOptions.map((option) => {
                const Icon = option.icon;
                const isSelected = preference === option.value;

                return (
                  <button
                    type="button"
                    key={option.value}
                    className={
                      isSelected
                        ? "theme-option selected"
                        : "theme-option"
                    }
                    onClick={() => setPreference(option.value)}
                    aria-pressed={isSelected}
                  >
                    <Icon size={22} />
                    <strong>{option.label}</strong>
                    <span>{option.description}</span>
                    {isSelected && <CheckCircle2 size={18} />}
                  </button>
                );
              })}
            </div>

            <div className="profile-card-actions">
              <button
                type="submit"
                className="primary-button"
                disabled={isSavingProfile}
              >
                {isSavingProfile ? "Saving..." : "Save profile"}
              </button>
            </div>
          </form>

          <section className="surface-card profile-section-card">
            <div className="section-heading-row">
              <div>
                <p className="eyebrow">Email security</p>
                <h2>Verification status</h2>
                <p>
                  Verified email addresses can securely recover their
                  account.
                </p>
              </div>
              <ShieldCheck size={22} />
            </div>

            {user.is_verified ? (
              <div className="verified-account-row">
                <BadgeCheck size={20} />
                <div>
                  <strong>Email verified</strong>
                  <span>
                    {user.email_verified_at
                      ? `Verified ${formatDate(user.email_verified_at)}`
                      : "Your address is verified."}
                  </span>
                </div>
              </div>
            ) : (
              <div className="profile-action-row">
                <div>
                  <strong>{user.email}</strong>
                  <span>Verification is still pending.</span>
                </div>
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => void handleVerificationRequest()}
                  disabled={isSendingVerification}
                >
                  <Send size={17} />
                  {isSendingVerification
                    ? "Preparing..."
                    : "Send verification"}
                </button>
              </div>
            )}
          </section>

          <form
            className="surface-card profile-section-card"
            onSubmit={handlePasswordChange}
          >
            <div className="section-heading-row">
              <div>
                <p className="eyebrow">Password</p>
                <h2>Change password</h2>
                <p>
                  Changing your password signs out every other active
                  session.
                </p>
              </div>
              <KeyRound size={22} />
            </div>

            <div className="profile-form-grid password-grid">
              <label>
                Current password
                <input
                  type="password"
                  value={currentPassword}
                  onChange={(event) =>
                    setCurrentPassword(event.target.value)
                  }
                  autoComplete="current-password"
                  required
                />
              </label>
              <label>
                New password
                <input
                  type="password"
                  value={newPassword}
                  onChange={(event) =>
                    setNewPassword(event.target.value)
                  }
                  minLength={10}
                  autoComplete="new-password"
                  required
                />
              </label>
              <label>
                Confirm new password
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(event) =>
                    setConfirmPassword(event.target.value)
                  }
                  minLength={10}
                  autoComplete="new-password"
                  required
                />
              </label>
            </div>

            <div className="profile-card-actions">
              <button
                type="submit"
                className="primary-button"
                disabled={isChangingPassword}
              >
                <KeyRound size={17} />
                {isChangingPassword
                  ? "Updating..."
                  : "Change password"}
              </button>
            </div>
          </form>

          <section className="surface-card profile-section-card">
            <div className="section-heading-row">
              <div>
                <p className="eyebrow">Active sessions</p>
                <h2>Devices signed into your account</h2>
                <p>
                  Revoke sessions you do not recognize or sign out
                  everywhere.
                </p>
              </div>
              <Laptop2 size={22} />
            </div>

            <div className="session-list">
              {sessions.map((session) => (
                <article className="session-row" key={session.id}>
                  <span className="session-device-icon">
                    <Laptop2 size={19} />
                  </span>
                  <div>
                    <strong>
                      {sessionName(session.user_agent)}
                      {session.current && (
                        <span className="current-session-badge">
                          Current
                        </span>
                      )}
                    </strong>
                    <span>
                      Last active {formatDate(session.last_used_at)} · IP{" "}
                      {session.ip_address}
                    </span>
                  </div>
                  {!session.current && (
                    <button
                      type="button"
                      className="text-button danger-text"
                      onClick={() =>
                        void handleRevokeSession(session.id)
                      }
                      disabled={busySessionId === session.id}
                    >
                      {busySessionId === session.id
                        ? "Revoking..."
                        : "Revoke"}
                    </button>
                  )}
                </article>
              ))}
            </div>

            <div className="profile-card-actions split-actions">
              <button
                type="button"
                className="secondary-button"
                onClick={() => void loadProfile()}
              >
                <RefreshCw size={17} />
                Refresh sessions
              </button>
              <button
                type="button"
                className="danger-outline-button"
                onClick={() => void handleLogoutAll()}
              >
                <LogOut size={17} />
                Sign out everywhere
              </button>
            </div>

            {currentSession && (
              <p className="muted-note">
                Current session expires {formatDate(currentSession.expires_at)}.
              </p>
            )}
          </section>

          <section className="surface-card profile-section-card">
            <div className="section-heading-row">
              <div>
                <p className="eyebrow">Security activity</p>
                <h2>Recent account events</h2>
                <p>
                  Review sign-ins, password changes and session actions.
                </p>
              </div>
              <ShieldCheck size={22} />
            </div>

            <div className="security-event-list">
              {events.length === 0 ? (
                <p className="muted-note">No security events yet.</p>
              ) : (
                events.slice(0, 12).map((event) => (
                  <article key={event.id} className="security-event-row">
                    <span className="event-dot" />
                    <div>
                      <strong>
                        {eventLabels[event.event_type] ??
                          event.event_type.replaceAll("_", " ")}
                      </strong>
                      <span>
                        {formatDate(event.created_at)} · {event.ip_address}
                      </span>
                    </div>
                  </article>
                ))
              )}
            </div>
          </section>

          <section className="surface-card profile-section-card account-actions-card">
            <div>
              <p className="eyebrow">Account session</p>
              <h2>Sign out from this device</h2>
              <p>
                Your refresh session is revoked immediately and the
                secure cookies are cleared.
              </p>
            </div>

            <button
              type="button"
              className="secondary-button"
              onClick={() => void signOut()}
            >
              <LogOut size={18} />
              Sign out
            </button>
          </section>

          <section className="surface-card profile-section-card danger-zone-card">
            <div className="section-heading-row">
              <div>
                <p className="eyebrow danger-text">Danger zone</p>
                <h2>Delete account permanently</h2>
                <p>
                  This deletes your documents, chunks, embeddings, Wiki
                  pages, sessions and account settings.
                </p>
              </div>
              <Trash2 size={22} />
            </div>

            <div className="profile-form-grid">
              <label>
                Password
                <input
                  type="password"
                  value={deletePassword}
                  onChange={(event) =>
                    setDeletePassword(event.target.value)
                  }
                  autoComplete="current-password"
                />
              </label>
              <label>
                Type DELETE
                <input
                  type="text"
                  value={deleteConfirmation}
                  onChange={(event) =>
                    setDeleteConfirmation(event.target.value)
                  }
                  placeholder="DELETE"
                />
              </label>
            </div>

            <div className="profile-card-actions">
              <button
                type="button"
                className="danger-button"
                disabled={
                  !deletePassword || deleteConfirmation !== "DELETE"
                }
                onClick={() => setIsDeleteDialogOpen(true)}
              >
                <Trash2 size={17} />
                Delete my account
              </button>
            </div>
          </section>
        </div>
      ) : null}

      <ConfirmDialog
        isOpen={isDeleteDialogOpen}
        title="Delete your entire account?"
        description={
          "This is permanent. Documents, embeddings, Wiki knowledge and " +
          "account data cannot be recovered."
        }
        confirmLabel="Delete permanently"
        isBusy={isDeleting}
        onClose={() => setIsDeleteDialogOpen(false)}
        onConfirm={() => void handleDeleteAccount()}
      />
    </section>
  );
}
