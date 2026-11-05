export function requestError(status: number, text: string) {
  let detail: unknown;
  try {
    detail = JSON.parse(text).detail;
  } catch {
    /* Non-JSON proxy error. */
  }
  if (status === 401)
    return typeof detail === "string"
      ? detail
      : "Session expired. Please sign in again.";
  if (Array.isArray(detail))
    return detail
      .map(
        (item) =>
          `${item.loc?.slice(1).join(".") || "Request"}: ${item.msg || "Invalid value"}`,
      )
      .join("; ");
  return typeof detail === "string"
    ? detail
    : `Request failed (${status}). Please try again.`;
}
export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch("/api" + path, {
    ...options,
    cache: "no-store",
    signal: options?.signal || AbortSignal.timeout(30000),
  });
  if (!response.ok) {
    if (response.status === 401 && path !== "/session")
      window.dispatchEvent(new Event("session-expired"));
    throw Error(requestError(response.status, await response.text()));
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
