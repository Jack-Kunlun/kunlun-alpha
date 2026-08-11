"use strict";
var __decorate = (this && this.__decorate) || function (decorators, target, key, desc) {
    var c = arguments.length, r = c < 3 ? target : desc === null ? desc = Object.getOwnPropertyDescriptor(target, key) : desc, d;
    if (typeof Reflect === "object" && typeof Reflect.decorate === "function") r = Reflect.decorate(decorators, target, key, desc);
    else for (var i = decorators.length - 1; i >= 0; i--) if (d = decorators[i]) r = (c < 3 ? d(r) : c > 3 ? d(target, key, r) : d(target, key)) || r;
    return c > 3 && r && Object.defineProperty(target, key, r), r;
};
var GlobalExceptionFilter_1;
Object.defineProperty(exports, "__esModule", { value: true });
exports.GlobalExceptionFilter = void 0;
const common_1 = require("@nestjs/common");
let GlobalExceptionFilter = GlobalExceptionFilter_1 = class GlobalExceptionFilter {
    logger = new common_1.Logger(GlobalExceptionFilter_1.name);
    catch(exception, host) {
        const ctx = host.switchToHttp();
        const response = ctx.getResponse();
        const request = ctx.getRequest();
        let status;
        let message;
        let code;
        if (exception instanceof common_1.HttpException) {
            status = exception.getStatus();
            const exResponse = exception.getResponse();
            message =
                typeof exResponse === "string"
                    ? exResponse
                    : exResponse["message"] ?? exception.message;
            code = common_1.HttpStatus[status] ?? "UNKNOWN_ERROR";
        }
        else {
            status = common_1.HttpStatus.INTERNAL_SERVER_ERROR;
            message = "Internal Server Error";
            code = "INTERNAL_SERVER_ERROR";
            if (exception instanceof Error) {
                this.logger.error(`Unhandled exception: ${exception.message}`, exception.stack);
            }
            else {
                this.logger.error(`Unhandled non-error exception: ${String(exception)}`);
            }
        }
        const body = {
            statusCode: status,
            message,
            code,
            timestamp: new Date().toISOString(),
            requestId: request.requestId ?? "unknown",
            path: request.url,
        };
        response.status(status).json(body);
    }
};
exports.GlobalExceptionFilter = GlobalExceptionFilter;
exports.GlobalExceptionFilter = GlobalExceptionFilter = GlobalExceptionFilter_1 = __decorate([
    (0, common_1.Catch)()
], GlobalExceptionFilter);
//# sourceMappingURL=http-exception.filter.js.map