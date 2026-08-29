import type { InstrumentBarsResponse } from "@kunlun/shared-types";
import { ForbiddenException, Inject, Injectable } from "@nestjs/common";
import {
  parseInstrumentBarsQuery,
  parseInstrumentId,
  type InstrumentIntelligenceClock,
} from "./instrument-intelligence.query";
import type { InstrumentIntelligenceAuthorizer } from "./instrument-intelligence.service";
import {
  INSTRUMENT_INTELLIGENCE_AUTHORIZER,
  INSTRUMENT_INTELLIGENCE_BARS,
  INSTRUMENT_INTELLIGENCE_CLOCK,
} from "./instrument-intelligence.tokens";
import type { InstrumentBarsReadModel, InstrumentDailyBar } from "./read-model.types";

export { AllowAllInstrumentIntelligenceAuthorizer } from "./instrument-intelligence.service";

function unique(values: readonly string[]): string[] {
  return [...new Set(values)].sort();
}

function latest(values: readonly string[]): string | null {
  return values.length === 0
    ? null
    : ([...values].sort((left, right) => Date.parse(right) - Date.parse(left))[0] ?? null);
}

function visible(bars: readonly InstrumentDailyBar[], asOf: string): void {
  const cutoff = Date.parse(asOf);
  if (!Number.isFinite(cutoff)) throw new Error("invalid point-in-time cutoff");
  let previousDate: string | null = null;
  for (const current of bars) {
    const eventTime = Date.parse(current.eventTime);
    const availableTime = Date.parse(current.availableTime);
    const processingTime = Date.parse(current.processingTime);
    if (
      !Number.isFinite(eventTime) ||
      !Number.isFinite(availableTime) ||
      !Number.isFinite(processingTime) ||
      eventTime > cutoff ||
      availableTime > cutoff ||
      processingTime > cutoff
    ) {
      throw new Error("point-in-time bars repository returned a future-visible record");
    }
    if (previousDate !== null && current.date <= previousDate) {
      throw new Error("point-in-time bars repository returned non-ascending dates");
    }
    previousDate = current.date;
  }
}

function response(
  instrumentId: string,
  query: ReturnType<typeof parseInstrumentBarsQuery>,
  bars: readonly InstrumentDailyBar[],
): InstrumentBarsResponse {
  visible(bars, query.effectiveAsOf);
  if (bars.length > query.limit) {
    throw new Error("point-in-time bars repository returned more rows than requested");
  }
  const dataCutoffTime = latest(bars.map((item) => item.eventTime));
  return {
    schemaVersion: "instrument-bars-v1",
    dataMeaning: "RESEARCH_ONLY_NO_REAL_ORDER_PATH",
    instrumentId,
    mode: query.mode,
    requestedAsOf: query.requestedAsOf,
    effectiveAsOf: query.effectiveAsOf,
    interval: "DAILY",
    priceType: "RAW",
    status: bars.length === 0 ? "EMPTY" : "AVAILABLE",
    barCount: bars.length,
    dataCutoffTime,
    freshnessSeconds:
      dataCutoffTime === null
        ? null
        : Math.max(
            0,
            Math.floor((Date.parse(query.effectiveAsOf) - Date.parse(dataCutoffTime)) / 1000),
          ),
    bars: [...bars],
    sourceVersions: unique(bars.map((item) => item.source + "@" + item.sourceVersion)),
    evidenceIds: unique(bars.map((item) => item.evidenceId)),
  };
}

@Injectable()
export class InstrumentBarsService {
  constructor(
    @Inject(INSTRUMENT_INTELLIGENCE_BARS)
    private readonly repository: InstrumentBarsReadModel,
    @Inject(INSTRUMENT_INTELLIGENCE_AUTHORIZER)
    private readonly authorizer: InstrumentIntelligenceAuthorizer,
    @Inject(INSTRUMENT_INTELLIGENCE_CLOCK)
    private readonly clock: InstrumentIntelligenceClock,
  ) {}

  async bars(
    rawInstrumentId: string,
    rawQuery: Record<string, unknown>,
  ): Promise<InstrumentBarsResponse> {
    if (!(await this.authorizer.canRead())) {
      throw new ForbiddenException("无权访问个股 Intelligence 日 K 线");
    }
    const instrumentId = parseInstrumentId(rawInstrumentId);
    const query = parseInstrumentBarsQuery(rawQuery, this.clock);
    const bars = await this.repository.load(instrumentId, query.effectiveAsOf, query.limit);
    return response(instrumentId, query, bars);
  }
}
