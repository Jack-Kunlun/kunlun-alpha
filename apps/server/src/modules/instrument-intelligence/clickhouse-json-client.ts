export interface ClickHouseIntelligenceConfig {
  url: string;
  database: string;
  user: string;
  timeoutMs: number;
  password?: string;
}

type FetchLike = (input: string | URL, init?: RequestInit) => Promise<Response>;

export class ClickHouseJsonClient {
  constructor(
    private readonly config: ClickHouseIntelligenceConfig,
    private readonly fetcher: FetchLike = fetch,
  ) {}

  async query(sql: string, parameters: Readonly<Record<string, string>>): Promise<unknown[]> {
    const url = new URL(this.config.url);
    url.searchParams.set("database", this.config.database);
    for (const [name, value] of Object.entries(parameters)) {
      url.searchParams.set("param_" + name, value);
    }
    const headers: Record<string, string> = {
      "content-type": "text/plain; charset=utf-8",
      "x-clickhouse-user": this.config.user,
    };
    if (this.config.password) headers["x-clickhouse-key"] = this.config.password;

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.config.timeoutMs);
    try {
      const response = await this.fetcher(url, {
        method: "POST",
        headers,
        body: sql,
        signal: controller.signal,
      });
      if (!response.ok) {
        throw new Error("ClickHouse instrument intelligence query failed (" + response.status + ")");
      }
      const body = await response.text();
      if (body.trim() === "") return [];
      return body
        .split(/\r?\n/)
        .filter(Boolean)
        .map((line) => {
          try {
            return JSON.parse(line) as unknown;
          } catch {
            throw new Error("ClickHouse instrument intelligence returned invalid JSON");
          }
        });
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") {
        throw new Error(
          "ClickHouse instrument intelligence timed out after " +
            String(this.config.timeoutMs) +
            "ms",
        );
      }
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }
}
