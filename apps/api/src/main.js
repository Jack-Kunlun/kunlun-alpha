"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
require("reflect-metadata");
const core_1 = require("@nestjs/core");
const common_1 = require("@nestjs/common");
const swagger_1 = require("@nestjs/swagger");
const app_module_1 = require("./app.module");
const http_exception_filter_1 = require("./common/filters/http-exception.filter");
const request_id_interceptor_1 = require("./common/interceptors/request-id.interceptor");
const env_1 = require("./env");
async function bootstrap() {
    const logger = new common_1.Logger("Bootstrap");
    const app = await core_1.NestFactory.create(app_module_1.AppModule);
    app.setGlobalPrefix("api/v1");
    app.useGlobalFilters(new http_exception_filter_1.GlobalExceptionFilter());
    app.useGlobalInterceptors(new request_id_interceptor_1.RequestIdInterceptor());
    app.useGlobalPipes(new common_1.ValidationPipe({
        whitelist: true,
        forbidNonWhitelisted: true,
        transform: true,
    }));
    if (!env_1.env.isProduction) {
        app.enableCors({ origin: "http://localhost:5173" });
    }
    const config = new swagger_1.DocumentBuilder()
        .setTitle("昆仑智策 API")
        .setDescription("Kunlun Alpha — A-Share Intelligence & Quant Platform")
        .setVersion("0.0.0")
        .build();
    const document = swagger_1.SwaggerModule.createDocument(app, config);
    swagger_1.SwaggerModule.setup("api/docs", app, document);
    await app.listen(env_1.env.port);
    logger.log(`API running on http://localhost:${env_1.env.port}`);
    logger.log(`Swagger docs at http://localhost:${env_1.env.port}/api/docs`);
}
bootstrap().catch((err) => {
    console.error("Failed to bootstrap:", err);
    process.exit(1);
});
//# sourceMappingURL=main.js.map