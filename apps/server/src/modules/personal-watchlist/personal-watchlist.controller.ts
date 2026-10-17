import {
  Body,
  Controller,
  Get,
  Header,
  Inject,
  Post,
  Req,
  UnauthorizedException,
} from "@nestjs/common";
import type { AuthenticatedRequest } from "../auth/auth.request";
import { PersonalWatchlistRepository } from "./personal-watchlist.repository";
import { parseWatchlistImport } from "./personal-watchlist.validation";
function owner(request: AuthenticatedRequest): string {
  if (!request.authSession) throw new UnauthorizedException("请先登录");
  return request.authSession.response.user.userId;
}
@Controller("personal-watchlist")
export class PersonalWatchlistController {
  constructor(
    @Inject(PersonalWatchlistRepository) private readonly repository: PersonalWatchlistRepository,
  ) {}
  @Get()
  @Header("Cache-Control", "no-store")
  list(@Req() request: AuthenticatedRequest) {
    return this.repository.list(owner(request));
  }
  @Post("import")
  @Header("Cache-Control", "no-store")
  importItems(@Req() request: AuthenticatedRequest, @Body() body: unknown) {
    return this.repository.importItems(owner(request), parseWatchlistImport(body));
  }
}
