import type { TranslationValues } from "next-intl";

/**
 * A next-intl translator scoped to the `Common.timeAgo` namespace.
 * Matches the type returned by `useTranslations("Common.timeAgo")`.
 */
type TimeAgoTranslator = (key: string, values?: TranslationValues) => string;

/**
 * Shared "time ago" helper.
 *
 * Buckets an elapsed duration into seconds / minutes / hours / days and renders
 * it via the `Common.timeAgo` message catalog (ICU-pluralized). Both
 * ProjectCard and AgentCard use this so the granularity and plural rules stay
 * consistent.
 *
 * @param input  A Date, ISO string, or null. Null → `never`.
 * @param t      A next-intl translator scoped to `Common.timeAgo`. Keys used:
 *               `justNow`, `seconds`, `minutes`, `hours`, `days`, `never`.
 */
export function timeAgo(
  input: Date | string | null,
  t: TimeAgoTranslator
): string {
  if (!input) return t("never");

  const date = typeof input === "string" ? new Date(input) : input;
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);

  if (seconds < 5) return t("justNow");
  if (seconds < 60) return t("seconds", { count: seconds });
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return t("minutes", { count: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t("hours", { count: hours });
  return t("days", { count: Math.floor(hours / 24) });
}
