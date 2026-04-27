import type { NextConfig } from "next";

const backendBaseUrl =
  process.env.BACKEND_API_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  (process.env.NODE_ENV === "development"
    ? "http://localhost:8001"
    : "https://ai-financial-operator-production.up.railway.app");

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendBaseUrl}/api/:path*`,
      },
      {
      source: '/api/prediction-markets',
      destination: '/api/prediction-markets',  // no-op, lets Next.js handle it
      },
    ];
  },
};

export default nextConfig;
