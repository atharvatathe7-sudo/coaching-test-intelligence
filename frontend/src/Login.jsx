import { useState } from "react";

import { apiFetch } from "./api";

export default function Login({ notice, onSignedIn }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");

    try {
      const data = await apiFetch("/api/auth/login", {
        method: "POST",
        json: { email, password },
        skipAuthRedirect: true,
      });
      setPassword("");
      onSignedIn(data.user);
    } catch (err) {
      setError(
        err.status === 401
          ? "Invalid email or password."
          : "Could not sign in. Check that the server is running."
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={submit}>
        <div className="brand">Coaching Test Intelligence</div>
        <div className="brand-subtitle">Sign in to continue</div>

        {notice && <div className="login-notice">{notice}</div>}

        <label className="login-field">
          <span>Email</span>
          <input
            autoComplete="username"
            onChange={(e) => setEmail(e.target.value)}
            required
            type="email"
            value={email}
          />
        </label>

        <label className="login-field">
          <span>Password</span>
          <input
            autoComplete="current-password"
            onChange={(e) => setPassword(e.target.value)}
            required
            type="password"
            value={password}
          />
        </label>

        {error && <div className="login-error">{error}</div>}

        <button className="login-submit" disabled={busy} type="submit">
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
