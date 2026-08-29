import type { AuthSessionResponse } from "@kunlun/shared-types";
import {
  Body,
  Controller,
  Get,
  Header,
  HttpCode,
  HttpStatus,
  Inject,
  Post,
  Req,
  Res,
  UnauthorizedException,
} from "@nestjs/common";
import { ApiOperation, ApiTags } from "@nestjs/swagger";
import { IsString, MaxLength, MinLength } from "class-validator";
import type { Response } from "express";
import type { AuthConfig } from "./auth.config";
import type { AuthenticatedRequest } from "./auth.request";
import { AuthService } from "./auth.service";
import { AUTH_CONFIG } from "./auth.tokens";
import { PublicRoute } from "./public-route.decorator";

export class AuthLoginDto {
  @IsString()
  @MinLength(3)
  @MaxLength(80)
  username!: string;

  @IsString()
  @MinLength(12)
  @MaxLength(256)
  password!: string;
}

@ApiTags("auth")
@Controller("auth")
export class AuthController {
  constructor(
    @Inject(AuthService) private readonly authService: AuthService,
    @Inject(AUTH_CONFIG) private readonly config: AuthConfig,
  ) {}

  @Post("login")
  @PublicRoute()
  @HttpCode(HttpStatus.OK)
  @Header("Cache-Control", "no-store")
  @ApiOperation({ summary: "Create a local research-terminal administrator session" })
  async login(
    @Body() input: AuthLoginDto,
    @Res({ passthrough: true }) response: Response,
  ): Promise<AuthSessionResponse> {
    const result = await this.authService.login(input.username, input.password);
    response.cookie(this.config.cookieName, result.sessionToken, this.cookieOptions());
    return result.response;
  }

  @Get("session")
  @Header("Cache-Control", "no-store")
  @ApiOperation({ summary: "Read and renew the authenticated browser session" })
  session(@Req() request: AuthenticatedRequest): AuthSessionResponse {
    if (request.authSession === undefined) throw new UnauthorizedException("请先登录");
    return request.authSession.response;
  }

  @Post("logout")
  @HttpCode(HttpStatus.OK)
  @Header("Cache-Control", "no-store")
  @ApiOperation({ summary: "Revoke the current authenticated browser session" })
  async logout(
    @Req() request: AuthenticatedRequest,
    @Res({ passthrough: true }) response: Response,
  ): Promise<{ authenticated: false }> {
    if (request.authSession === undefined) throw new UnauthorizedException("请先登录");
    await this.authService.logout(request.authSession.sessionDigest);
    response.clearCookie(this.config.cookieName, this.cookieOptions());
    return { authenticated: false };
  }

  private cookieOptions() {
    return {
      httpOnly: true,
      secure: this.config.secureCookie,
      sameSite: "strict" as const,
      path: "/",
    };
  }
}
