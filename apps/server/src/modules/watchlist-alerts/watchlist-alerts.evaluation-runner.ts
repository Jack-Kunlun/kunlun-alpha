import { createHash } from "node:crypto";
import type { InstrumentBarsResponse, WatchlistAlertEvaluationRun } from "@kunlun/shared-types";
import {
  Inject,
  Injectable,
  Logger,
  type OnModuleDestroy,
  type OnModuleInit,
} from "@nestjs/common";
import { InstrumentBarsService } from "../instrument-intelligence/instrument-bars.service";
import { WATCHLIST_ALERTS_EVALUATION_INTERVAL_MS } from "./watchlist-alerts.tokens";
import type { WatchlistAlertRule } from "./watchlist-alerts.types";
import { WatchlistAlertsService } from "./watchlist-alerts.service";

type AlertsPort = Pick<WatchlistAlertsService, "workspace" | "evaluate">;
type BarsPort = Pick<InstrumentBarsService, "bars">;

@Injectable()
export class WatchlistAlertsEvaluationRunner implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(WatchlistAlertsEvaluationRunner.name);
  private timer: ReturnType<typeof setInterval> | null = null;
  private inFlight: Promise<WatchlistAlertEvaluationRun> | null = null;

  constructor(
    @Inject(WatchlistAlertsService) private readonly alerts: AlertsPort,
    @Inject(InstrumentBarsService) private readonly instrumentBars: BarsPort,
    @Inject(WATCHLIST_ALERTS_EVALUATION_INTERVAL_MS) private readonly intervalMs: number,
  ) {}

  onModuleInit(): void {
    if (this.intervalMs === 0) return;
    void this.runOnce().catch(() => this.logger.warn("initial watchlist evaluation failed"));
    this.timer = setInterval(() => {
      void this.runOnce().catch(() => this.logger.warn("scheduled watchlist evaluation failed"));
    }, this.intervalMs);
    this.timer.unref();
  }

  onModuleDestroy(): void {
    if (this.timer !== null) clearInterval(this.timer);
    this.timer = null;
  }

  runOnce(): Promise<WatchlistAlertEvaluationRun> {
    if (this.inFlight !== null) return this.inFlight;
    const running = this.evaluateLatest().finally(() => {
      if (this.inFlight === running) this.inFlight = null;
    });
    this.inFlight = running;
    return running;
  }

  private async evaluateLatest(): Promise<WatchlistAlertEvaluationRun> {
    const workspace = await this.alerts.workspace();
    const barsByInstrument = new Map<string, Promise<InstrumentBarsResponse>>();
    let evaluated = 0;
    let skippedUnsupported = 0;
    let skippedNoData = 0;
    let failed = 0;

    for (const rule of workspace.rules) {
      if (!rule.enabled) continue;
      if (rule.condition.field !== "LAST_PRICE" && rule.condition.field !== "CHANGE_BPS") {
        skippedUnsupported += 1;
        continue;
      }
      for (const instrumentId of rule.instrumentIds) {
        try {
          let pending = barsByInstrument.get(instrumentId);
          if (pending === undefined) {
            pending = this.instrumentBars.bars(instrumentId, { mode: "CURRENT", limit: "2" });
            barsByInstrument.set(instrumentId, pending);
          }
          const bars = await pending;
          const evaluation = latestEvaluation(rule, bars);
          if (evaluation === null) {
            skippedNoData += 1;
            continue;
          }
          await this.alerts.evaluate(evaluation);
          evaluated += 1;
        } catch {
          failed += 1;
          this.logger.warn(`watchlist evaluation failed for ${rule.ruleId}/${instrumentId}`);
        }
      }
    }

    return {
      schemaVersion: "watchlist-alert-evaluation-run-v1",
      generatedAt: new Date().toISOString(),
      rulesScanned: workspace.rules.length,
      evaluated,
      skippedUnsupported,
      skippedNoData,
      failed,
      dataMeaning: "RESEARCH_ALERT_EVALUATION_NO_ORDER_PATH",
    };
  }
}

function latestEvaluation(
  rule: WatchlistAlertRule,
  response: InstrumentBarsResponse,
): Parameters<WatchlistAlertsService["evaluate"]>[0] | null {
  const latest = response.bars.at(-1);
  if (latest === undefined) return null;
  const field = rule.condition.field;
  let observedValue: string;
  if (field === "LAST_PRICE") {
    observedValue = latest.close;
  } else if (field === "CHANGE_BPS") {
    const previous = response.bars.at(-2);
    if (previous === undefined) return null;
    observedValue = changeBps(latest.close, previous.close);
  } else {
    return null;
  }
  const availableTime = [latest.availableTime, latest.processingTime].sort(
    (left, right) => Date.parse(right) - Date.parse(left),
  )[0];
  if (availableTime === undefined) return null;
  const eventId = createHash("sha256")
    .update(`daily-bar\u0000${response.instrumentId}\u0000${latest.evidenceId}\u0000${field}`)
    .digest("hex");
  return {
    ruleId: rule.ruleId,
    eventId,
    instrumentId: response.instrumentId,
    field,
    featureName: null,
    observedValue,
    eventTime: latest.eventTime,
    availableTime,
  };
}

function decimalParts(value: string): { integer: bigint; scale: number } {
  if (!/^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(value)) {
    throw new Error("bar close must be a non-negative decimal");
  }
  const [whole = "0", fraction = ""] = value.split(".");
  return { integer: BigInt(whole + fraction), scale: fraction.length };
}

function changeBps(currentValue: string, previousValue: string): string {
  const current = decimalParts(currentValue);
  const previous = decimalParts(previousValue);
  const scale = Math.max(current.scale, previous.scale);
  const currentInteger = current.integer * 10n ** BigInt(scale - current.scale);
  const previousInteger = previous.integer * 10n ** BigInt(scale - previous.scale);
  if (previousInteger <= 0n) throw new Error("previous close must be positive");
  const numerator = (currentInteger - previousInteger) * 10_000n;
  const sign = numerator < 0n ? -1n : 1n;
  const rounded = sign * ((numerator * sign + previousInteger / 2n) / previousInteger);
  return rounded.toString();
}
