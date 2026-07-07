import type { NextConfig } from "next";

// NEXT_DIST_DIR lets a second dev instance (e.g. preview/verification) run without
// colliding with the primary dev server's .next directory.
const nextConfig: NextConfig = {
  distDir: process.env.NEXT_DIST_DIR || ".next",
};

export default nextConfig;
