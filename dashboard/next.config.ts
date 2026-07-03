import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./i18n/request.ts");

const nextConfig: NextConfig = {
  // Pin Turbopack's workspace root to this directory. Otherwise, when a stray
  // lockfile exists in a parent dir (e.g. ~/package-lock.json), Turbopack infers
  // the wrong root and the RSC server/client bundlers compute mismatched module
  // IDs — producing "Could not find the module … in the React Client Manifest".
  turbopack: {
    root: __dirname,
  },
};

export default withNextIntl(nextConfig);
