import { Injectable } from "@nestjs/common";
import type { CallHandler, ExecutionContext, NestInterceptor } from "@nestjs/common";
import type { Observable } from "rxjs";
import { tap } from "rxjs";
import { randomUUID } from "node:crypto";
import { apiMetrics } from "../../metrics";

@Injectable()
export class RequestIdInterceptor implements NestInterceptor {
  intercept(context: ExecutionContext, next: CallHandler): Observable<unknown> {
    const request = context.switchToHttp().getRequest<{
      requestId?: string;
      headers: Record<string, string | undefined>;
      method: string;
      path: string;
    }>();
    const response = context.switchToHttp().getResponse<{
      statusCode: number;
      setHeader(name: string, value: string): void;
    }>();
    request.requestId =
      request.headers["x-request-id"] ??
      (request.headers["x-correlation-id"] as string) ??
      randomUUID();
    response.setHeader("x-request-id", request.requestId);
    const started = performance.now();
    return next.handle().pipe(
      tap({
        finalize: () =>
          apiMetrics.recordHttpRequest(
            request.method,
            request.path,
            response.statusCode,
            (performance.now() - started) / 1000,
          ),
      }),
    );
  }
}
