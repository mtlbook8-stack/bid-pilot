/// <reference types="vite/client" />

/**
 * Typed Vite environment variables exposed to the SPA. Only `VITE_`-prefixed
 * vars are injected at build time (see .env.example).
 */
interface ImportMetaEnv {
  readonly VITE_ENTRA_CLIENT_ID: string;
  readonly VITE_ENTRA_TENANT_ID: string;
  readonly VITE_API_SCOPE: string;
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
