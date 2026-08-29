import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AuthenticatedTerminal, AuthProvider } from "./features/auth/auth-context";
import "./index.css";

const root = document.getElementById("root");
if (!root) {
  throw new Error("Root element #root not found in document");
}

createRoot(root).render(
  <StrictMode>
    <AuthProvider>
      <AuthenticatedTerminal />
    </AuthProvider>
  </StrictMode>,
);
