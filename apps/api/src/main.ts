import "reflect-metadata";

import { NestFactory } from "@nestjs/core";
import { ValidationPipe, Logger } from "@nestjs/common";
import { DocumentBuilder, SwaggerModule } from "@nestjs/swagger";
import { AppModule } from "./app.module";
import { GlobalExceptionFilter } from "./common/filters/http-exception.filter";
import { RequestIdInterceptor } from "./common/interceptors/request-id.interceptor";
import { env } from "./env";

async function bootstrap(): Promise<void> {
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

  if (!env.isProduction) {
    app.enableCors({ origin: "http://localhost:5173" });
  }

  const config = new DocumentBuilder()
    .setTitle("昆仑智策 API")
    .setDescription("Kunlun Alpha — A-Share Intelligence & Quant Platform")
    .setVersion("0.0.0")
    .build();
  const document = SwaggerModule.createDocument(app, config);
  SwaggerModule.setup("api/docs", app, document);

  await app.listen(env.port);
  logger.log(`API running on http://localhost:${env.port}`);
  logger.log(`Swagger docs at http://localhost:${env.port}/api/docs`);
}

bootstrap().catch((err: unknown) => {
  console.error("Failed to bootstrap:", err);
  process.exit(1);
});
