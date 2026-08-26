export interface DashboardAuthorizer {
  canAccess(): boolean | Promise<boolean>;
}

export class DenyAllDashboardAuthorizer implements DashboardAuthorizer {
  canAccess(): boolean {
    return false;
  }
}

/** Explicit deployment opt-in for the anonymous viewer's terminal:read capability. */
export class PublicReadDashboardAuthorizer implements DashboardAuthorizer {
  canAccess(): boolean {
    return true;
  }
}
