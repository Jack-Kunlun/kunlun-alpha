type MetricKey = `${string}\u0000${string}\u0000${number}`;

function escapeLabel(value: string): string {
  return value.replaceAll("\\", "\\\\").replaceAll('"', '\\"').replaceAll("\n", "\\n");
}

export class MetricsRegistry {
  private readonly requests = new Map<MetricKey, number>();
  private readonly durations = new Map<MetricKey, number>();

  constructor(private readonly prefix: string) {}

  recordHttpRequest(method: string, route: string, status: number, durationSeconds: number): void {
    const key: MetricKey = `${method}\u0000${route}\u0000${status}`;
    this.requests.set(key, (this.requests.get(key) ?? 0) + 1);
    this.durations.set(key, (this.durations.get(key) ?? 0) + durationSeconds);
  }

  render(): string {
    const lines = [
      `# HELP ${this.prefix}_http_requests_total Total HTTP requests.`,
      `# TYPE ${this.prefix}_http_requests_total counter`,
    ];
    for (const [key, count] of this.requests) {
      const [method, route, status] = key.split("\u0000") as [string, string, string];
      const labels = `method="${escapeLabel(method)}",route="${escapeLabel(route)}",status="${status}"`;
      lines.push(`${this.prefix}_http_requests_total{${labels}} ${count}`);
    }
    lines.push(
      `# HELP ${this.prefix}_http_request_duration_seconds_sum Cumulative HTTP request duration.`,
      `# TYPE ${this.prefix}_http_request_duration_seconds_sum counter`,
    );
    for (const [key, duration] of this.durations) {
      const [method, route, status] = key.split("\u0000") as [string, string, string];
      const labels = `method="${escapeLabel(method)}",route="${escapeLabel(route)}",status="${status}"`;
      lines.push(`${this.prefix}_http_request_duration_seconds_sum{${labels}} ${duration}`);
    }
    return `${lines.join("\n")}\n`;
  }
}
