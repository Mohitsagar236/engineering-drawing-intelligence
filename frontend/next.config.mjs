const backend = process.env.API_INTERNAL_URL || "http://127.0.0.1:8000";
export default {
  output: process.env.STANDALONE_BUILD === "true" ? "standalone" : undefined,
  poweredByHeader: false,
  experimental: {
    // The API allows MAX_UPLOAD_MB up to 200 MiB. Include multipart overhead
    // so Next never truncates a request that the API would otherwise accept.
    proxyClientMaxBodySize: 201 * 1024 * 1024,
    proxyTimeout: 120000,
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: backend + "/api/:path*" }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "same-origin" },
          { key: "X-Frame-Options", value: "DENY" },
        ],
      },
    ];
  },
};
