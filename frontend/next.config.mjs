/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  webpack: (config, { dev }) => {
    // Polling can desync webpack chunks on macOS; only enable in Docker / broken FSEvents.
    if (dev && process.env.NEXT_WEBPACK_POLL === "1") {
      config.watchOptions = {
        poll: 2000,
        aggregateTimeout: 600,
      };
    }
    return config;
  },
};

export default nextConfig;
