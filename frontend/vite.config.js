import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react-swc";
var DEV_BACKEND_TARGET = "http://127.0.0.1:8000";
var DEV_PROXY_ERROR_BODY = JSON.stringify({
    detail: "ShortMaker API is not reachable at http://127.0.0.1:8000. Start FastAPI or set VITE_API_BASE_URL.",
});
var DEV_PROXY_PREFIXES = [
    "/capabilities",
    "/session",
    "/jobs",
    "/process",
    "/trends",
    "/shorts",
    "/youtube",
    "/ai",
];
function createDevProxyOptions() {
    return {
        target: DEV_BACKEND_TARGET,
        changeOrigin: true,
        configure: function (proxy) {
            proxy.on("error", function (_error, _req, res) {
                if (!res || res.writableEnded)
                    return;
                if (!res.headersSent) {
                    res.writeHead(503, {
                        "Content-Type": "application/json; charset=utf-8",
                        "Cache-Control": "no-store",
                    });
                }
                res.end(DEV_PROXY_ERROR_BODY);
            });
        },
    };
}
export default defineConfig(function (_a) {
    var mode = _a.mode;
    var env = loadEnv(mode, process.cwd(), "");
    var useDevProxy = !(env.VITE_API_BASE_URL || "").trim();
    return {
        plugins: [react()],
        build: {
            outDir: "dist",
            emptyOutDir: true,
        },
        server: {
            port: 5173,
            proxy: useDevProxy
                ? Object.fromEntries(DEV_PROXY_PREFIXES.map(function (prefix) { return [
                    prefix,
                    createDevProxyOptions(),
                ]; }))
                : undefined,
        },
    };
});
