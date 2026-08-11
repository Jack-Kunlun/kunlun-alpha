"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.env = void 0;
function requireEnv(key) {
    const value = process.env[key];
    if (!value) {
        throw new Error(`Missing required environment variable: ${key}`);
    }
    return value;
}
exports.env = {
    port: parseInt(process.env["PORT"] ?? "3001", 10),
    nodeEnv: process.env["NODE_ENV"] ?? "development",
    get isProduction() {
        return this.nodeEnv === "production";
    },
};
//# sourceMappingURL=env.js.map