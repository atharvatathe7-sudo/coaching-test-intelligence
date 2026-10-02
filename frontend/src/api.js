// Shared API client.
//
// - Sends the session cookie (same-origin; the token is never visible to JS).
// - Adds the CSRF header to every non-GET request (required by the server).
// - Supports AbortSignal so stale requests can be cancelled.
// - Parses JSON and throws ApiError with the server's message.
// - Routes 401 responses to one handler (shows the login screen).
// - Leaves FormData bodies alone so the browser sets the multipart boundary.

const SAFE_METHODS = new Set(["GET", "HEAD"]);

export class ApiError extends Error {
  constructor(status, message, data) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
  }
}

let unauthorizedHandler = null;

export function setUnauthorizedHandler(handler) {
  unauthorizedHandler = handler;
}

export function isAbortError(error) {
  return error?.name === "AbortError";
}

function messageFrom(data, fallback) {
  const detail = data?.detail;

  if (typeof detail === "string") return detail;

  if (typeof detail?.message === "string") return detail.message;

  if (Array.isArray(detail) && detail.length) {
    return detail.map((item) => item.msg).join(" ");
  }

  return fallback;
}

export async function apiFetch(
  path,
  { method = "GET", json, body, signal, skipAuthRedirect = false } = {}
) {
  const headers = {};

  if (!SAFE_METHODS.has(method)) {
    headers["X-Requested-With"] = "fetch";
  }

  let payload = body;

  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(json);
  }

  const response = await fetch(path, {
    method,
    headers,
    body: payload,
    signal,
    credentials: "same-origin",
  });

  const text = await response.text();
  let data = null;

  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }

  if (response.status === 401 && !skipAuthRedirect && unauthorizedHandler) {
    unauthorizedHandler();
  }

  if (!response.ok) {
    throw new ApiError(
      response.status,
      messageFrom(data, `Request failed (${response.status}).`),
      data
    );
  }

  return data;
}
