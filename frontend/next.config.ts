import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Self-contained server bundle for a small production Docker image.
  output: "standalone",
  poweredByHeader: false,
  devIndicators: false,
};

export default nextConfig;
