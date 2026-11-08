import { formatNumber, locale, t } from "../i18n";
export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}
let csrf = "";
export function setCSRF(value: string) {
  csrf = value;
}
export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const binary = body instanceof Blob;
  const headers: Record<string, string> = { "Accept-Language": locale };
  if (method !== "GET") headers["X-CSRF-Token"] = csrf;
  if (body !== undefined)
    headers["Content-Type"] = binary
      ? "application/octet-stream"
      : "application/json";
  if (binary)
    headers["X-Chunk-SHA256"] = await sha256(await body.arrayBuffer());
  const response = await fetch(`/api${path}`, {
    method,
    headers,
    credentials: "same-origin",
    signal,
    body: body === undefined ? undefined : binary ? body : JSON.stringify(body),
  });
  const value = await response.json();
  if (!response.ok) {
    if (
      response.status === 401 &&
      path !== "/auth/login" &&
      !path.startsWith("/public/")
    )
      window.dispatchEvent(new Event("session-expired"));
    const message =
      typeof value.detail === "string"
        ? value.detail
        : t("输入内容不符合要求，请检查后重试");
    throw new ApiError(message, response.status);
  }
  return value as T;
}
export async function sha256(data: ArrayBuffer): Promise<string> {
  if (!crypto.subtle)
    throw new Error(t("上传需要 HTTPS 安全连接；本地开发请使用 localhost"));
  return [...new Uint8Array(await crypto.subtle.digest("SHA-256", data))]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
export async function fingerprint(file: File) {
  const metadata = new TextEncoder().encode(
    `${file.name}\0${file.size}\0${file.lastModified}\0`,
  );
  const sample = new Blob([
    metadata,
    file.slice(0, 1024 ** 2),
    file.slice(Math.max(0, file.size - 1024 ** 2)),
  ]);
  return sha256(await sample.arrayBuffer());
}
export const formatSize = (size: number) => {
  if (size < 1024) return `${size} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = size / 1024;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index++;
  }
  return `${formatNumber(Number(value.toFixed(value >= 10 ? 1 : 2)))} ${units[index]}`;
};
export const date = (value: number) =>
  new Intl.DateTimeFormat(locale, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(value * 1000);
export const errorText = (error: unknown) =>
  error instanceof Error ? error.message : t("操作失败，请重试");
export const dateTime = (value: number) =>
  new Intl.DateTimeFormat(locale, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(value * 1000);
