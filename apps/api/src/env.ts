export const env = {
  port: parseInt(process.env["PORT"] ?? "3001", 10),
  nodeEnv: process.env["NODE_ENV"] ?? "development",
  get isProduction() {
    return this.nodeEnv === "production";
  },
} as const;
