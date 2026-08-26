import { Injectable } from "@nestjs/common";

export interface LimitPoolAuthorizer {
  canRead(request: unknown): boolean | Promise<boolean>;
}

@Injectable()
export class EnvironmentLimitPoolAuthorizer implements LimitPoolAuthorizer {
  canRead(): boolean {
    return process.env["DASHBOARD_TERMINAL_READ_POLICY"] === "public";
  }
}
