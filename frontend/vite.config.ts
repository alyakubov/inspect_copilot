import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: proxy /api to the FastAPI server so the SPA and API are same-origin
// (cookies work, no CORS dance). Prod: FastAPI serves the built bundle.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8001",
        changeOrigin: true,
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        // Split heavy libraries into separate, individually-cacheable chunks.
        // Combined with route-level lazy loading, charts/maps/markdown/datagrid
        // are fetched only when their page is opened.
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (id.includes("recharts") || id.includes("/d3-") || id.includes("victory"))
            return "charts";
          if (id.includes("leaflet")) return "maps";
          if (
            id.includes("react-markdown") ||
            id.includes("remark") ||
            id.includes("micromark") ||
            id.includes("mdast") ||
            id.includes("hast") ||
            id.includes("unist") ||
            id.includes("decode-named-character-reference") ||
            id.includes("property-information")
          )
            return "markdown";
          if (id.includes("@mui/x-data-grid")) return "datagrid";
          if (id.includes("@mui") || id.includes("@emotion")) return "mui";
          return "vendor";
        },
      },
    },
  },
});
