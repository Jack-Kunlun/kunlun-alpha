import {
  ForbiddenException,
  Inject,
  Injectable,
  ServiceUnavailableException,
  UnauthorizedException,
} from "@nestjs/common";
import type { CanActivate, ExecutionContext } from "@nestjs/common";
import { Reflector } from "@nestjs/core";
import type { AuthConfig, BrowserRequestHeaders } from "./auth.config";
import {
  assertInternalServiceRequest,
  assertTrustedBrowserRequest,
  readCookieToken,
} from "./auth.config";
import type { AuthenticatedRequest } from "./auth.request";
import { AuthService } from "./auth.service";
import { AUTH_CONFIG } from "./auth.tokens";
import { PUBLIC_ROUTE_METADATA } from "./public-route.decorator";
import { INTERNAL_SERVICE_ROUTE_METADATA } from "./internal-service-route.decorator";

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

function oneHeader(value: string | string[] | undefined): string | undefined {
  if (Array.isArray(value)) return value.length === 1 ? value[0] : undefined;
  return value;
}

function browserHeaders(request: AuthenticatedRequest): BrowserRequestHeaders {
  return {
    origin: oneHeader(request.headers.origin),
    referer: oneHeader(request.headers.referer),
    secFetchSite: oneHeader(request.headers["sec-fetch-site"]),
    secFetchMode: oneHeader(request.headers["sec-fetch-mode"]),
    secFetchDest: oneHeader(request.headers["sec-fetch-dest"]),
  };
}

@Injectable()
export class AuthenticationGuard implements CanActivate {
  constructor(
    @Inject(Reflector) private readonly reflector: Reflector,
    @Inject(AuthService) private readonly authService: AuthService,
    @Inject(AUTH_CONFIG) private readonly config: AuthConfig,
  ) {}

  async canActivate(context: ExecutionContext): Promise<boolean> {
    const request = context.switchToHttp().getRequest<AuthenticatedRequest>();
    const isPublic =
      this.reflector.getAllAndOverride<boolean>(PUBLIC_ROUTE_METADATA, [
        context.getHandler(),
        context.getClass(),
      ]) === true;

    const internalService = this.reflector.getAllAndOverride<string | undefined>(
      INTERNAL_SERVICE_ROUTE_METADATA,
      [context.getHandler(), context.getClass()],
    );
    if (internalService !== undefined) {
      if (internalService !== "market-data-settings") {
        throw new ForbiddenException("内部服务路由不可用");
      }
      try {
        assertInternalServiceRequest(
          {
            ...browserHeaders(request),
            authorization: request.headers.authorization,
            cookie: request.headers.cookie,
            csrfToken: request.headers["x-csrf-token"],
          },
          request.method,
          request.originalUrl ?? request.url,
          this.config.marketDataSettingsWorkerToken,
        );
      } catch {
        if (this.config.marketDataSettingsWorkerToken === undefined) {
          throw new ServiceUnavailableException("内部服务未配置");
        }
        throw new UnauthorizedException("内部服务认证失败");
      }
      return true;
    }

    if (isPublic) {
      if (!SAFE_METHODS.has(request.method.toUpperCase())) this.assertBrowser(request);
      return true;
    }

    const sessionToken = readCookieToken(request.headers.cookie, this.config.cookieName);
    if (sessionToken === null) throw new UnauthorizedException("请先登录");
    const authenticated = await this.authService.authenticate(sessionToken);
    request.authSession = authenticated;
    request.authSessionToken = sessionToken;

    if (!SAFE_METHODS.has(request.method.toUpperCase())) {
      this.assertBrowser(request);
      this.authService.assertCsrf(sessionToken, oneHeader(request.headers["x-csrf-token"]));
    }
    return true;
  }

  private assertBrowser(request: AuthenticatedRequest): void {
    try {
      assertTrustedBrowserRequest(browserHeaders(request), this.config.publicOrigin);
    } catch {
      throw new ForbiddenException("请求来源验证失败");
    }
  }
}
