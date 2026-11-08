import { en } from "./en";

export type Locale = "zh-CN" | "en";

export function detectLocale(languages: readonly string[]): Locale {
  for (const language of languages) {
    const base = language.toLowerCase().split(/[-_]/)[0];
    if (base === "zh") return "zh-CN";
    if (base === "en") return "en";
  }
  return "en";
}

export const locale = detectLocale(
  typeof navigator === "undefined"
    ? []
    : navigator.languages?.length
      ? navigator.languages
      : [navigator.language],
);

export const formatNumber = (value: number) =>
  new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(value);

export function t(
  message: keyof typeof en,
  values: Record<string, string | number | undefined> = {},
): string {
  const template = locale === "zh-CN" ? message : en[message];
  return template.replace(/\{(\w+)\}/g, (_, key: string) => {
    const value = values[key];
    return typeof value === "number" ? formatNumber(value) : (value ?? "");
  });
}
