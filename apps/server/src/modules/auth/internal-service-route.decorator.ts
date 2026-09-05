import { SetMetadata } from "@nestjs/common";

export const INTERNAL_SERVICE_ROUTE_METADATA = "kunlun:auth:internal-service-route";

export type InternalServiceRouteName = "market-data-settings";

/**
 * Marks a narrow internal-service route for the global authentication guard.
 * This is intentionally separate from PublicRoute: browser sessions and
 * browser-origin requests must never authenticate this route.
 */
export const InternalServiceRoute = (service: InternalServiceRouteName) =>
  SetMetadata(INTERNAL_SERVICE_ROUTE_METADATA, service);
