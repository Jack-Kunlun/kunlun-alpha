import { ForbiddenException, Inject, Injectable } from "@nestjs/common";
import type { MarketEmotionSnapshot, SectorRotationEvent } from "./emotion-snapshot";
import { AllowAllEmotionAuthorizer, type EmotionAuthorizer } from "./emotion-authorizer";
import type { EmotionRepository } from "./emotion-repository";
import { validateEmotionQuery } from "./emotion-query";
import { EMOTION_AUTHORIZER, EMOTION_REPOSITORY } from "./emotion.tokens";

@Injectable()
export class EmotionService {
  constructor(
    @Inject(EMOTION_REPOSITORY) private readonly repository: EmotionRepository,
    @Inject(EMOTION_AUTHORIZER)
    private readonly authorizer: EmotionAuthorizer = new AllowAllEmotionAuthorizer(),
  ) {}

  async snapshots(input: unknown): Promise<MarketEmotionSnapshot[]> {
    await this.assertAuthorized();
    return this.repository.querySnapshots(validateEmotionQuery(input));
  }

  async rotationEvents(input: unknown): Promise<SectorRotationEvent[]> {
    await this.assertAuthorized();
    return this.repository.queryRotationEvents(validateEmotionQuery(input));
  }

  async versions(): Promise<string[]> {
    await this.assertAuthorized();
    return this.repository.listVersions();
  }

  private async assertAuthorized(): Promise<void> {
    if (!(await this.authorizer.canAccess())) {
      throw new ForbiddenException("无权访问市场情绪与轮动回放");
    }
  }
}
