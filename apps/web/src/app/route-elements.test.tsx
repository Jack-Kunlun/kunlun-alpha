import { isValidElement, Suspense, type ReactElement } from "react";
import { describe, expect, it } from "vitest";
import { terminalRoutes } from "./route-contract";
import { terminalRouteElements } from "./route-elements";

describe("terminalRouteElements", () => {
  it.each(terminalRoutes.map((route) => route.id))(
    "loads %s behind a route-level Suspense boundary",
    (routeId) => {
      const boundary = terminalRouteElements[routeId];
      expect(isValidElement(boundary)).toBe(true);
      expect((boundary as ReactElement).type).toBe(Suspense);

      const page = (boundary as ReactElement<{ children: ReactElement }>).props.children;
      expect(page.type).toMatchObject({ $$typeof: Symbol.for("react.lazy") });
    },
  );
});
