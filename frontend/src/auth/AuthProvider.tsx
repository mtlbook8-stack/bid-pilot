import { ReactNode, useMemo } from "react";
import {
  PublicClientApplication,
  Configuration,
  LogLevel,
  InteractionType,
  AccountInfo,
} from "@azure/msal-browser";
import { MsalProvider } from "@azure/msal-react";

/**
 * AuthProvider wires Microsoft Entra ID (Azure AD) SSO into the SPA via MSAL.
 *
 * Configuration comes entirely from Vite env vars (see .env.example):
 *   - VITE_ENTRA_CLIENT_ID  — the app registration's client id
 *   - VITE_ENTRA_TENANT_ID  — the directory (tenant) id
 *   - VITE_API_SCOPE        — the protected-API scope requested for access tokens
 *
 * The PublicClientApplication is built once and memoised so React never
 * recreates MSAL state across re-renders (which would drop the cached account).
 */

const clientId = import.meta.env.VITE_ENTRA_CLIENT_ID ?? "";
const tenantId = import.meta.env.VITE_ENTRA_TENANT_ID ?? "";

/** The single scope the API expects on the bearer token. Exported for the client. */
export const API_SCOPE =
  import.meta.env.VITE_API_SCOPE ?? `api://${clientId}/access_as_user`;

/** Login request shared by the login button and silent token acquisition. */
export const loginRequest = {
  scopes: [API_SCOPE],
};

const msalConfig: Configuration = {
  auth: {
    clientId,
    authority: `https://login.microsoftonline.com/${tenantId}`,
    redirectUri: window.location.origin,
    postLogoutRedirectUri: window.location.origin,
  },
  cache: {
    // sessionStorage keeps tokens scoped to the tab and avoids leaking them to
    // other origins; acceptable here because the SPA is single-page.
    cacheLocation: "sessionStorage",
    storeAuthStateInCookie: false,
  },
  system: {
    loggerOptions: {
      // Surface only errors to the console — verbose MSAL logs are noise in prod.
      logLevel: LogLevel.Error,
      loggerCallback: (level, message, containsPii) => {
        if (containsPii) return;
        if (level === LogLevel.Error) console.error(message);
      },
    },
  },
};

/** Shared MSAL instance. Exported so the API client can pull a token outside React. */
export const msalInstance = new PublicClientApplication(msalConfig);

// Pre-select an account if one is already cached so the first token request
// has a known account to act against (MSAL requires this for silent flows).
const cachedAccounts = msalInstance.getAllAccounts();
if (cachedAccounts.length > 0) {
  msalInstance.setActiveAccount(cachedAccounts[0]);
}

export const interactionType = InteractionType.Redirect;

/**
 * Acquire an API access token silently, falling back to a redirect when the
 * cached token is stale and no account interaction is possible. Used by the
 * fetch-based API client which lives outside the React tree.
 */
export async function acquireApiToken(): Promise<string | null> {
  const account: AccountInfo | null =
    msalInstance.getActiveAccount() ?? msalInstance.getAllAccounts()[0] ?? null;
  if (!account) return null;
  try {
    const result = await msalInstance.acquireTokenSilent({
      ...loginRequest,
      account,
    });
    return result.accessToken;
  } catch {
    // Silent failed (expired refresh / consent change) — kick off interactive.
    await msalInstance.acquireTokenRedirect({ ...loginRequest, account });
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  // useMemo guards against any accidental re-instantiation on hot reload.
  const instance = useMemo(() => msalInstance, []);
  return <MsalProvider instance={instance}>{children}</MsalProvider>;
}
