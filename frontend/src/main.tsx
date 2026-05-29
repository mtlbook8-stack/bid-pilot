import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider, msalInstance } from "@/auth/AuthProvider";
import App from "@/App";
import "@/index.css";

/**
 * Application entry point. Composition order matters:
 *   MsalProvider (auth) → QueryClientProvider (server state) → BrowserRouter
 * so every route and query can read the auth context and acquire tokens.
 *
 * MSAL must finish handling any redirect response before React renders, so we
 * await initialize() (v3 requirement) before mounting.
 */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Bids/projects don't change second-to-second; a short stale window cuts
      // refetch noise while keeping the UI fresh on navigation.
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

async function bootstrap(): Promise<void> {
  await msalInstance.initialize();
  // Process the auth code if we're returning from a redirect sign-in.
  await msalInstance.handleRedirectPromise();

  const container = document.getElementById("root");
  if (!container) throw new Error("Root element #root not found");

  createRoot(container).render(
    <StrictMode>
      <AuthProvider>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </QueryClientProvider>
      </AuthProvider>
    </StrictMode>
  );
}

void bootstrap();
