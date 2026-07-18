import path from "node:path";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { loadEnv, type PluginOption } from "vite";
import { defineConfig } from "vitest/config";

const plugins: PluginOption[] = [react(), tailwindcss()];

function apiProxyTarget(env: Record<string, string>) {
	if (env.API_PROXY_TARGET) return env.API_PROXY_TARGET;
	return `http://127.0.0.1:${env.BACKEND_PORT || "8001"}`;
}

export default defineConfig(({ mode }) => {
	const env = loadEnv(mode, process.cwd(), "");
	return {
		plugins,
		resolve: {
			alias: {
				"@": path.resolve(__dirname, "./src"),
			},
		},
		server: {
			proxy: {
				"/api": {
					target: apiProxyTarget(env),
					changeOrigin: true,
				},
			},
		},
		build: {
			chunkSizeWarningLimit: 600,
			rolldownOptions: {
				output: {
					codeSplitting: {
						groups: [
							{
								name: "react-vendor",
								test: /node_modules\/(react|react-dom|react-router|@tanstack\/react-query)\//,
							},
							{
								name: "ui-vendor",
								test: /node_modules\/(@base-ui\/react|@tanstack\/react-table)\//,
							},
							{ name: "chart-vendor", test: /node_modules\/recharts\// },
						],
					},
				},
			},
		},
		test: {
			globals: true,
			environment: "jsdom",
			setupFiles: ["./src/test-setup.ts"],
			include: ["src/**/*.{test,spec}.{ts,tsx}"],
			testTimeout: 15_000,
			clearMocks: true,
			// MSW's setupServer is process-local; parallel files racing on
			// server.use/resetHandlers produce intermittent auth fixture bleed.
			fileParallelism: false,
		},
	};
});
