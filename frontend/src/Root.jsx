import { useEffect, useState } from "react";

import App from "./App.jsx";
import Login from "./Login.jsx";
import { apiFetch, setUnauthorizedHandler } from "./api";

export default function Root() {
  // undefined = still checking the session, null = signed out.
  const [user, setUser] = useState(undefined);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    // Any 401 from any request (expired or revoked session) signs out.
    setUnauthorizedHandler(() => {
      setNotice("Your session has ended. Please sign in again.");
      setUser(null);
    });

    apiFetch("/api/auth/me", { skipAuthRedirect: true })
      .then((data) => setUser(data.user))
      .catch(() => setUser(null));

    return () => setUnauthorizedHandler(null);
  }, []);

  async function logout() {
    try {
      await apiFetch("/api/auth/logout", {
        method: "POST",
        skipAuthRedirect: true,
      });
    } catch {
      // Signed out locally either way.
    }
    setNotice("");
    setUser(null);
  }

  if (user === undefined) {
    return <div className="login-page">Loading…</div>;
  }

  if (user === null) {
    return (
      <Login
        notice={notice}
        onSignedIn={(signedIn) => {
          setNotice("");
          setUser(signedIn);
        }}
      />
    );
  }

  // key={user.id}: a different user gets a completely fresh App, so no
  // data loaded for the previous user survives.
  return <App key={user.id} onLogout={logout} user={user} />;
}
