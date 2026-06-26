import createMiddleware from "next-intl/middleware";
import { routing } from "@/i18n/routing";

/**
 * Next.js 16 locale negotiation proxy (this was called `middleware.ts` before
 * Next 16). Detects the user's preferred locale from the request and prepends
 * it to the path, redirecting e.g. `/projects/x` → `/en/projects/x`.
 *
 * The matcher intentionally excludes `_next` internals, static assets, and
 * dot-files (favicon, etc.) so those requests bypass locale handling.
 */
export default createMiddleware(routing);

export const config = {
  matcher: ["/((?!_next|_vercel|.*\\..*).*)"],
};
