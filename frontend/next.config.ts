import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  distDir: process.env.NEXT_BUILD_DIR || ".next",
  // The native Windows launcher runs `next start`; standalone tracing needs symlink rights there.
  output: process.env.LOCALCLIP_NATIVE ? undefined : "standalone",
  typescript: {
    ignoreBuildErrors: false,
  },
};

export default nextConfig;
