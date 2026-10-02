import { ApiError, apiFetch } from "./api";

// Sends one CSV import request and always returns a report object.
export async function postImport(path, fields, file) {
  const form = new FormData();

  Object.entries(fields).forEach(([key, value]) => {
    form.append(key, String(value));
  });
  form.append("file", file);

  try {
    const report = await apiFetch(`/api/imports/${path}`, {
      method: "POST",
      body: form,
    });

    if (!report?.status) throw new Error("Unexpected response.");

    return report;
  } catch (err) {
    return {
      status: "invalid",
      errors: [
        {
          file: "",
          message:
            err instanceof ApiError
              ? err.message
              : "Could not reach the server. Check that the backend is running and try again.",
        },
      ],
      warnings: [],
      summary: {},
    };
  }
}
