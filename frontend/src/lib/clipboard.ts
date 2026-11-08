import { t } from "../i18n";
export async function copyText(value: string) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return;
    } catch {
      /* Fall back for browsers denying async clipboard access. */
    }
  }
  const input = document.createElement("textarea");
  input.value = value;
  input.style.position = "fixed";
  input.style.opacity = "0";
  document.body.appendChild(input);
  try {
    input.select();
    if (!document.execCommand("copy"))
      throw new Error(t("复制失败，请手动复制链接"));
  } finally {
    input.remove();
  }
}
export const absoluteShareUrl = (path: string) =>
  new URL(path, window.location.origin).href;
