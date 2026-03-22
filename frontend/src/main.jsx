import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ClerkProvider } from "@clerk/react";
import App from "./App";
import "./index.css";

const publishableKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY;
const isAdminConsoleRoute =
  typeof window !== "undefined" && window.location.pathname.startsWith("/ashmil2010");

createRoot(document.getElementById("root")).render(
  <StrictMode>
    {isAdminConsoleRoute ? (
      <App adminStandalone />
    ) : (
      <ClerkProvider publishableKey={publishableKey}>
        <App />
      </ClerkProvider>
    )}
  </StrictMode>,
);
