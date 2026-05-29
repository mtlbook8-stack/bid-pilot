import { useMsal } from "@azure/msal-react";
import { LogOut, User } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * Header — the top bar. Shows the signed-in account and a sign-out action.
 * Page-specific titles live in PageShell, keeping the header purely about
 * identity/session so it stays stable across navigation.
 */
export function Header() {
  const { instance, accounts } = useMsal();
  const account = accounts[0];
  const name = account?.name ?? account?.username ?? "Signed in";

  const signOut = () => {
    void instance.logoutRedirect({
      postLogoutRedirectUri: window.location.origin,
    });
  };

  return (
    <header className="flex h-14 shrink-0 items-center justify-end gap-3 border-b bg-card px-4">
      <div className="flex items-center gap-2 text-sm">
        <span className="flex size-7 items-center justify-center rounded-full bg-muted text-muted-foreground">
          <User className="size-4" />
        </span>
        <span className="hidden max-w-[200px] truncate text-muted-foreground sm:inline">
          {name}
        </span>
      </div>
      <Button variant="ghost" size="sm" onClick={signOut} aria-label="Sign out">
        <LogOut className="size-4" />
        <span className="hidden sm:inline">Sign out</span>
      </Button>
    </header>
  );
}
