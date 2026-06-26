import type { Metadata } from "next";
import { Geist_Mono, IBM_Plex_Sans_Arabic } from "next/font/google";
import { notFound } from "next/navigation";
import { NextIntlClientProvider, hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import "../globals.css";
import { Sidebar } from "@/components/sidebar";
import { WebSocketProvider } from "@/lib/use-websocket";
import { routing, isRtl, type Locale } from "@/i18n/routing";

// Latin font — used for LTR (English). Geist Mono has no Arabic glyphs.
const geistMono = Geist_Mono({ subsets: ["latin"], variable: "--font-latin" });
// Arabic-capable font — applied when dir=rtl. Falls back to latin vars.
const arabicSans = IBM_Plex_Sans_Arabic({
  subsets: ["arabic", "latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-arabic",
});

// Pre-render both locales.
export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "Metadata" });
  return {
    title: t("title"),
    description: t("description"),
  };
}

export default async function LocaleLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;

  // Reject unknown locales with the nearest 404.
  if (!hasLocale(routing.locales, locale)) {
    notFound();
  }

  // Tell next-intl which locale is active for this (static) render.
  setRequestLocale(locale);

  const rtl = isRtl(locale);
  const fontClass = rtl ? arabicSans.className : geistMono.className;

  return (
    <html
      lang={locale}
      dir={rtl ? "rtl" : "ltr"}
      className={`dark ${geistMono.variable} ${arabicSans.variable}`}
      // Suppression is intentional: next/font injects its generated class
      // names on the client during hydration, which can briefly differ from
      // the server-rendered markup. All attributes here (lang/dir/className)
      // are deterministic from `locale` — there is no theme/localStorage
      // branching — so this masks only the font-loader artifact, not a real
      // server/client divergence.
      suppressHydrationWarning
    >
      <body
        className={`${fontClass} bg-zinc-950 text-zinc-100 antialiased`}
      >
        <NextIntlClientProvider>
          <WebSocketProvider>
            <div className="flex">
              <Sidebar />
              <main className="flex-1 p-6">{children}</main>
            </div>
          </WebSocketProvider>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}

// Keep the Locale type reachable for downstream modules.
export type { Locale };
