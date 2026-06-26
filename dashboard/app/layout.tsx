/**
 * Root layout — pass-through.
 *
 * The `<html>`/`<body>` tags live in `app/[locale]/layout.tsx` so that the
 * locale-dependent `lang` and `dir` attributes are set correctly. This file
 * exists because Next.js requires a root layout component.
 */
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
