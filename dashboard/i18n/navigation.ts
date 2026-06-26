import { createNavigation } from "next-intl/navigation";
import { routing } from "./routing";

/**
 * Locale-aware navigation primitives. Use these INSTEAD of `next/link` and
 * `next/navigation` everywhere in the app:
 *
 *   import { Link, useRouter, usePathname } from "@/i18n/navigation";
 *
 * `Link href="/projects/x"` automatically becomes `/ar/projects/x` for Arabic.
 * `usePathname()` returns the path WITHOUT the locale prefix, so existing
 * active-link comparisons like `pathname === '/projects'` keep working.
 */
export const { Link, redirect, usePathname, useRouter, getPathname } =
  createNavigation(routing);
