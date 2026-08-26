import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { resolveBootstrapTerminalRoles } from "./app/access-control";
import { App } from "./App";
import "./index.css";

const root = document.getElementById("root");
if (!root) {
  throw new Error("Root element #root not found in document");
}

const bootstrap = (window as Window & { __KUNLUN_SESSION__?: { roles?: unknown } })
  .__KUNLUN_SESSION__;
const roles = resolveBootstrapTerminalRoles({
  development: import.meta.env.DEV,
  sessionRoles: bootstrap?.roles,
});

createRoot(root).render(
  <StrictMode>
    <App roles={roles} />
  </StrictMode>,
);
