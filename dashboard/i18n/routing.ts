import { defineRouting } from "next-intl/routing";

/**
 * Locale routing config.
 *
 * `en` is the default/fallback; `ar` is Arabic (RTL). The locale lives in the
 * URL path (e.g. `/ar/projects/x`), so links are shareable and survive reload.
 */
export const routing = defineRouting({
  locales: ["en", "ar"],
  defaultLocale: "en",
});

export type Locale = (typeof routing.locales)[number];

export const LOCALE_LABELS: Record<Locale, string> = {
  en: "EN",
  ar: "ع",
};

export function isRtl(locale: string): boolean {
  return locale === "ar";
}
