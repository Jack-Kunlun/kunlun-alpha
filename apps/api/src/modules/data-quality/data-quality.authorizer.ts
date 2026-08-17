/**
 * Data-quality authorization boundary.
 *
 * The service consults an authorizer before returning any data. An
 * authorization failure is surfaced as a controlled forbidden response — never
 * as an empty success or a leaked exception.
 */

export interface DataQualityAuthorizer {
  canAccess(): boolean | Promise<boolean>;
}

export class AllowAllAuthorizer implements DataQualityAuthorizer {
  canAccess(): boolean {
    return true;
  }
}
