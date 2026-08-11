import {
  Injectable,
  NestInterceptor,
  ExecutionContext,
  CallHandler,
} from "@nestjs/common";
import { Observable } from "rxjs";
import { randomUUID } from "node:crypto";

@Injectable()
export class RequestIdInterceptor implements NestInterceptor {
  intercept(context: ExecutionContext, next: CallHandler): Observable<unknown> {
    const request = context.switchToHttp().getRequest<{
      requestId?: string;
      headers: Record<string, string | undefined>;
    }>();
    request.requestId =
      request.headers["x-request-id"] ??
      (request.headers["x-correlation-id"] as string) ??
      randomUUID();
    return next.handle();
  }
}
