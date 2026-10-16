import "reflect-metadata";

import { NestFactory } from "@nestjs/core";
import { ValidationPipe, Logger } from "@nestjs/common";
import { DocumentBuilder, SwaggerModule } from "@nestjs/swagger";
import { AppModule } from "./app.module";
import { GlobalExceptionFilter } from "./common/filters/http-exception.filter";
import { RequestIdInterceptor } from "./common/interceptors/request-id.interceptor";
import { env } from "./env";
import { initTelemetry } from "@kunlun/observability";
import type { AuthConfig } from "./modules/auth/auth.config";
import { AUTH_CONFIG } from "./modules/auth/auth.tokens";
import { APP_VERSION } from "./app-version";

async function bootstrap(): Promise<void> {
  const telemetry = initTelemetry({
    serviceName: "kunlun-server",
    serviceVersion: APP_VERSION,
    otlpEndpoint: process.env["OTEL_EXPORTER_OTLP_ENDPOINT"],
  });
  const logger = new Logger("Bootstrap");

  const app = await NestFactory.create(AppModule);

  app.setGlobalPrefix("api/v1");

  app.useGlobalFilters(new GlobalExceptionFilter());
  app.useGlobalInterceptors(new RequestIdInterceptor());
  app.useGlobalPipes(
    new ValidationPipe({
      whitelist: true,
      forbidNonWhitelisted: true,
      transform: true,
    }),
  );

  const authConfig = app.get<AuthConfig>(AUTH_CONFIG);
  app.enableCors({
    origin: authConfig.publicOrigin,
    credentials: true,
    allowedHeaders: ["content-type", "x-csrf-token", "x-request-id"],
  });

  if (!env.isProduction) {
    const config = new DocumentBuilder()
      .setTitle("昆仑智策 API")
      .setDescription("Kunlun Alpha — A-Share Intelligence & Quant Platform")
      .setVersion(APP_VERSION)
      .build();
    const document = SwaggerModule.createDocument(app, config);
    SwaggerModule.setup("api/docs", app, document);
    logger.log(`Swagger docs at http://localhost:${env.port}/api/docs`);
  }

  await app.listen(env.port);
  app.enableShutdownHooks();
  const shutdown = async () => telemetry.shutdown();
  process.once("SIGTERM", shutdown);
  process.once("SIGINT", shutdown);
  logger.log(`Server running on http://localhost:${env.port}`);
}

bootstrap().catch((err: unknown) => {
  console.error("Failed to bootstrap:", err);
  process.exit(1);
});
