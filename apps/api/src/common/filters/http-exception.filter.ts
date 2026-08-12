import { Catch, HttpException, HttpStatus, Logger } from "@nestjs/common";
import type { ArgumentsHost, ExceptionFilter } from "@nestjs/common";
import type { Request, Response } from "express";
import type { ErrorResponseDto } from "../dto/error-response.dto";

@Catch()
export class GlobalExceptionFilter implements ExceptionFilter {
  private readonly logger = new Logger(GlobalExceptionFilter.name);

  catch(exception: unknown, host: ArgumentsHost): void {
    const ctx = host.switchToHttp();
    const response = ctx.getResponse<Response>();
    const request = ctx.getRequest<Request & { requestId?: string }>();

    let status: number;
    let message: string;
    let code: string;

    if (exception instanceof HttpException) {
      status = exception.getStatus();
      const exResponse = exception.getResponse();
      message =
        typeof exResponse === "string"
          ? exResponse
          : (((exResponse as Record<string, unknown>)["message"] as string) ?? exception.message);
      code = HttpStatus[status] ?? "UNKNOWN_ERROR";
    } else {
      status = HttpStatus.INTERNAL_SERVER_ERROR;
      message = "Internal Server Error";
      code = "INTERNAL_SERVER_ERROR";

      if (exception instanceof Error) {
        this.logger.error(`Unhandled exception: ${exception.message}`, exception.stack);
      } else {
        this.logger.error(`Unhandled non-error exception: ${String(exception)}`);
      }
    }

    const body: ErrorResponseDto = {
      statusCode: status,
      message,
      code,
      timestamp: new Date().toISOString(),
      requestId: request.requestId ?? "unknown",
      path: request.url,
    };

    response.status(status).json(body);
  }
}
