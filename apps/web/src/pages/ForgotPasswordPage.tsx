import {
  ArrowLeft,
  KeyRound,
  Mail,
} from "lucide-react";
import {
  useState,
  type FormEvent,
} from "react";
import {
  Link,
} from "react-router-dom";

import {
  requestPasswordReset,
} from "../api/auth";
import {
  getApiErrorMessage,
} from "../api/errors";
import FeedbackBanner from "../components/FeedbackBanner";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function handleSubmit(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault();
    setError("");
    setMessage("");
    setIsLoading(true);

    try {
      const result = await requestPasswordReset(email);
      setMessage(result.message);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main className="auth-layout auth-layout-single">
      <section className="auth-form-panel">
        <div className="auth-card">
          <span className="auth-icon-badge">
            <KeyRound size={22} />
          </span>
          <div className="auth-card-header">
            <p className="eyebrow">Account recovery</p>
            <h1>Reset your password</h1>
            <p>
              Enter your email and we will prepare a secure,
              single-use reset link.
            </p>
          </div>

          {message && (
            <FeedbackBanner kind="success" message={message} />
          )}
          {error && (
            <FeedbackBanner kind="error" message={error} />
          )}

          <form className="auth-form" onSubmit={handleSubmit}>
            <label>
              Email
              <div className="input-wrapper">
                <Mail size={18} />
                <input
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="name@company.com"
                  autoComplete="email"
                  required
                />
              </div>
            </label>

            <button
              type="submit"
              className="primary-button full-width"
              disabled={isLoading}
            >
              {isLoading ? "Preparing link..." : "Send reset link"}
            </button>
          </form>

          <Link className="auth-back-link" to="/">
            <ArrowLeft size={17} />
            Back to sign in
          </Link>
        </div>
      </section>
    </main>
  );
}
