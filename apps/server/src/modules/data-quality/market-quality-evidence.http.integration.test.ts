import { ValidationPipe, Module, type INestApplication } from "@nestjs/common";
import { NestFactory } from "@nestjs/core";
import { ServerResponse, type IncomingMessage, type Server } from "node:http";
import { Readable } from "node:stream";
import { afterEach, describe, expect, it } from "vitest";
import type { MarketQualityEvidencePage } from "@kunlun/shared-types";
import { DataQualityController } from "./data-quality.controller";
import { DataQualityService } from "./data-quality.service";
import { InMemoryQualityRepository } from "./in-memory-quality.repository";
import type { DataQualityAuthorizer } from "./data-quality.authorizer";
import {
  MarketQualityEvidenceNotFoundError,
  type MarketQualityEvidenceReadModel,
} from "./market-quality-evidence.read-model";

const page: MarketQualityEvidencePage = {
  schemaVersion: "market-quality-evidence-v1",
  snapshotId: "a".repeat(64),
  publishedAt: "2026-09-01T01:02:00.000001Z",
  snapshotRecordCount: 0,
  matchingRecordCount: 0,
  offset: 0,
  limit: 20,
  hasMore: false,
  records: [],
};

const availableModel: MarketQualityEvidenceReadModel = {
  list: async () => page,
  detail: async () => {
    throw new MarketQualityEvidenceNotFoundError();
  },
};

let app: INestApplication | undefined;

async function createApp(
  model: MarketQualityEvidenceReadModel,
  authorizer: DataQualityAuthorizer = { canAccess: () => true },
): Promise<INestApplication> {
  @Module({
    controllers: [DataQualityController],
    providers: [
      {
        provide: DataQualityService,
        useValue: new DataQualityService(
          new InMemoryQualityRepository(),
          authorizer,
          undefined,
          undefined,
          model,
        ),
      },
    ],
  })
  class DataQualityHttpTestModule {}

  app = await NestFactory.create(DataQualityHttpTestModule, { logger: false });
  app.setGlobalPrefix("api/v1");
  app.useGlobalPipes(
    new ValidationPipe({
      whitelist: true,
      forbidNonWhitelisted: true,
      transform: true,
    }),
  );
  await app.init();
  return app;
}

async function request(path: string): Promise<{ status: number; body: Record<string, unknown> }> {
  if (app === undefined) throw new Error("test app is not initialized");
  const server = app.getHttpServer() as Server;
  const requestStream = Readable.from([]);
  const socket = {
    destroyed: false,
    encrypted: false,
    remoteAddress: "127.0.0.1",
    remotePort: 32123,
  };
  Object.assign(requestStream, {
    method: "GET",
    url: `/api/v1${path}`,
    headers: {},
    httpVersion: "1.1",
    httpVersionMajor: 1,
    httpVersionMinor: 1,
    complete: false,
    aborted: false,
    socket,
    connection: socket,
  });
  const response = new ServerResponse(requestStream as IncomingMessage);
  const chunks: Buffer[] = [];
  Object.defineProperty(response, "headersSent", {
    configurable: true,
    enumerable: true,
    value: false,
    writable: true,
  });
  const responseWithCapture = response as ServerResponse & { headersSent: boolean };
  const responseAny = response as unknown as {
    end: (chunk?: unknown, encoding?: unknown, callback?: () => void) => ServerResponse;
    write: (chunk: unknown, encoding?: unknown, callback?: () => void) => boolean;
  };
  responseAny.write = (chunk: unknown) => {
    if (chunk !== undefined) chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk)));
    return true;
  };
  responseAny.end = (chunk?: unknown, _encoding?: unknown, callback?: () => void) => {
    if (chunk !== undefined) chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk)));
    responseWithCapture.headersSent = true;
    response.emit("finish");
    callback?.();
    return response;
  };
  const completed = new Promise<void>((resolve, reject) => {
    response.once("finish", resolve);
    response.once("error", reject);
  });
  server.emit("request", requestStream as unknown as IncomingMessage, response);
  await completed;
  const bodyText = Buffer.concat(chunks).toString("utf8");
  return {
    status: response.statusCode,
    body: JSON.parse(bodyText) as Record<string, unknown>,
  };
}

describe("market quality evidence HTTP boundary", () => {
  afterEach(async () => {
    await app?.close();
    app = undefined;
  });

  it("uses the real ValidationPipe and returns a safe success payload", async () => {
    await createApp(availableModel);
    await expect(request("/data-quality/market-evidence?source=akshare-tencent")).resolves.toEqual({
      status: 200,
      body: page,
    });
  });

  it("rejects unknown query fields with HTTP 400 before the reader", async () => {
    await createApp(availableModel);
    await expect(request("/data-quality/market-evidence?secretSentinel=x")).resolves.toMatchObject({
      status: 400,
    });
  });

  it("keeps forbidden and unavailable responses controlled", async () => {
    await createApp(availableModel, { canAccess: () => false });
    await expect(request("/data-quality/market-evidence")).resolves.toMatchObject({ status: 403 });

    await app?.close();
    app = undefined;
    const failingModel: MarketQualityEvidenceReadModel = {
      list: async () => {
        throw new Error("/private/secret-sentinel");
      },
      detail: async () => {
        throw new Error("/private/secret-sentinel");
      },
    };
    await createApp(failingModel);
    const unavailable = await request("/data-quality/market-evidence");
    expect(unavailable.status).toBe(503);
    expect(JSON.stringify(unavailable.body)).not.toContain("secret-sentinel");
  });
});
