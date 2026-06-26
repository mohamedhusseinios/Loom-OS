import { getRequestConfig } from "next-intl/server";
import { hasLocale } from "next-intl";
import { routing } from "./routing";

/**
 * Resolves the message bundle for the current request. Called by
 * `NextIntlClientProvider` (via `getLocale`/`getMessages`) and server hooks.
 */
export default getRequestConfig(async ({ requestLocale }) => {
  // `requestLocale` comes from the [locale] segment / middleware. Validate it;
  // fall back to the default if a bad value was injected.
  const requested = await requestLocale;
  const locale = hasLocale(routing.locales, requested)
    ? requested
    : routing.defaultLocale;

  return {
    locale,
    messages: (await import(`../messages/${locale}.json`)).default,
  };
});
