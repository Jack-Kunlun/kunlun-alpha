import type { ReactNode } from "react";
import { BrowserRouter, Route, Routes } from "react-router";
import {
  ANONYMOUS_TERMINAL_ROLES,
  TerminalAccessProvider,
  useTerminalRoles,
} from "@/app/access-control";
import { TerminalFilterProvider } from "@/app/filter-context";
import {
  canAccessTerminalRoute,
  getTerminalRoute,
  type TerminalRole,
  type TerminalRouteId,
  terminalRoutes,
} from "@/app/route-contract";
import { terminalRouteElements } from "@/app/route-elements";
import { Toaster } from "@/components/ui/sonner";
import { Layout } from "./components/Layout";
import { NotFound } from "./pages/NotFound";
import { Forbidden } from "./pages/Forbidden";

function ProtectedRoute({ routeId, children }: { routeId: TerminalRouteId; children: ReactNode }) {
  const roles = useTerminalRoles();
  return canAccessTerminalRoute(getTerminalRoute(routeId), roles) ? children : <Forbidden />;
}

function protectedPage(routeId: TerminalRouteId, children: ReactNode) {
  return <ProtectedRoute routeId={routeId}>{children}</ProtectedRoute>;
}

export function App({ roles = ANONYMOUS_TERMINAL_ROLES }: { roles?: readonly TerminalRole[] }) {
  return (
    <TerminalAccessProvider roles={roles}>
      <BrowserRouter>
        <Routes>
          <Route
            element={
              <TerminalFilterProvider>
                <Layout />
              </TerminalFilterProvider>
            }
          >
            {terminalRoutes.map((route) =>
              route.path === "/" ? (
                <Route
                  key={route.id}
                  index
                  element={protectedPage(route.id, terminalRouteElements[route.id])}
                />
              ) : (
                <Route
                  key={route.id}
                  path={route.path.slice(1)}
                  element={protectedPage(route.id, terminalRouteElements[route.id])}
                />
              ),
            )}
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
        <Toaster />
      </BrowserRouter>
    </TerminalAccessProvider>
  );
}
