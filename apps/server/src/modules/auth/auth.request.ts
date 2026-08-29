import type { Request } from "express";
import type { AuthenticatedSession } from "./auth.service";

export interface AuthenticatedRequest extends Request {
  authSession?: AuthenticatedSession;
  authSessionToken?: string;
}
