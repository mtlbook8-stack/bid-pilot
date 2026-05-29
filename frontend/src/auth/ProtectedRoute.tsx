import { ReactNode, useEffect } from "react";
import { useIsAuthenticated, useMsal } from "@azure/msal-react";
import { InteractionStatus } from "@azure/msal-browser";
import { loginRequest } from "./AuthProvider";
import { LoadingSkeleton } from "@/components/common/LoadingSkeleton";

/**
 * ProtectedRoute guards the authenticated area of the app.
 *
 * - While MSAL is mid-redirect (handling a login response) it shows a skeleton
 *   so we never flash a login prompt over an in-flight sign-in.
 * - When unauthenticated and idle, it triggers a redirect sign-in.
 * - When authenticated, it renders the protected children.
 */
export function ProtectedRoute({ children }: { children: ReactNode }) {
  const isAuthenticated = useIsAuthenticated();
  const { instance, inProgress } = useMsal();

  useEffect(() => {
    // Only start a login once MSAL is fully idle to avoid "interaction in
    // progress" errors when a redirect response is still being processed.
    if (!isAuthenticated && inProgress === InteractionStatus.None) {
      void instance.loginRedirect(loginRequest);
    }
  }, [isAuthenticated, inProgress, instance]);

  if (inProgress !== InteractionStatus.None) {
    return (
      <div className="p-8">
        <LoadingSkeleton lines={6} />
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-muted-foreground">
        Redirecting to sign in…
      </div>
    );
  }

  return <>{children}</>;
}
