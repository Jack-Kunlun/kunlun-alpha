import { createContext, type PropsWithChildren, useContext } from "react";
import type { TerminalRole } from "./route-contract";

export const ANONYMOUS_TERMINAL_ROLES: readonly TerminalRole[] = ["viewer"];

const TERMINAL_ROLES: readonly TerminalRole[] = [
  "viewer",
  "researcher",
  "paper_operator",
  "platform_admin",
];

export function resolveBootstrapTerminalRoles({
  development,
  sessionRoles,
}: {
  development: boolean;
  sessionRoles: unknown;
}): readonly TerminalRole[] {
  if (Array.isArray(sessionRoles)) {
    const validated = sessionRoles.filter(
      (role): role is TerminalRole =>
        typeof role === "string" && TERMINAL_ROLES.includes(role as TerminalRole),
    );
    if (validated.length === sessionRoles.length && validated.length > 0) {
      return [...new Set(validated)];
    }
    return ANONYMOUS_TERMINAL_ROLES;
  }
  return development ? ["platform_admin"] : ANONYMOUS_TERMINAL_ROLES;
}

const TerminalAccessContext = createContext<readonly TerminalRole[]>(
  ANONYMOUS_TERMINAL_ROLES,
);

export function TerminalAccessProvider({
  roles,
  children,
}: PropsWithChildren<{ roles: readonly TerminalRole[] }>) {
  return <TerminalAccessContext.Provider value={roles}>{children}</TerminalAccessContext.Provider>;
}

export function useTerminalRoles(): readonly TerminalRole[] {
  return useContext(TerminalAccessContext);
}
