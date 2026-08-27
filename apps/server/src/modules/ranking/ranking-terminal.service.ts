import {
  BadRequestException,
  Inject,
  Injectable,
  NotFoundException,
  ServiceUnavailableException,
} from "@nestjs/common";
import type { RankingTerminalSnapshot } from "@kunlun/shared-types";
import { RankingEngineHttpError, type RankingEngineClient } from "./ranking-engine.client";
import { RANKING_ENGINE_CLIENT } from "./ranking-terminal.tokens";

@Injectable()
export class RankingTerminalService {
  constructor(@Inject(RANKING_ENGINE_CLIENT) private readonly client: RankingEngineClient) {}

  async latest(asOf: unknown): Promise<RankingTerminalSnapshot> {
    const normalized = normalizeAsOf(asOf);
    try {
      return await this.client.latest(normalized);
    } catch (error) {
      if (error instanceof RankingEngineHttpError && error.status === 404) {
        throw new NotFoundException("当前没有已发布的 Ranking 快照");
      }
      if (error instanceof RankingEngineHttpError && error.status === 422) {
        throw new BadRequestException(error.message);
      }
      throw new ServiceUnavailableException("Ranking 快照服务暂不可用");
    }
  }
}

function normalizeAsOf(value: unknown): string | null {
  if (value === undefined || value === null || value === "") return null;
  if (typeof value !== "string") throw new BadRequestException("asOf must be RFC3339");
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.getTime()) || !/(?:Z|[+-][0-9]{2}:[0-9]{2})$/.test(value)) {
    throw new BadRequestException("asOf must be RFC3339 with timezone");
  }
  return parsed.toISOString();
}
