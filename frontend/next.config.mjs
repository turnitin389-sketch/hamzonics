/** @type {import('next').NextConfig} */
const apiUrl = process.env.API_INTERNAL_URL || "http://127.0.0.1:8000";

const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  // In production Nginx sends /api to FastAPI directly; this rewrite makes
  // `npm run dev` work the same way (same origin, so cookies just work).
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiUrl}/api/:path*` }];
  },
};

export default nextConfig;
