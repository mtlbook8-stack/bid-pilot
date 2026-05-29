import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  FolderKanban,
  FileStack,
  MailX,
  Mail,
  Plane,
} from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Sidebar — the persistent primary navigation. Highlights the active route via
 * NavLink's isActive state. Collapses to icons on narrow viewports so the
 * comparison page keeps maximum horizontal room on tablets.
 */
const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/projects", label: "Projects", icon: FolderKanban, end: false },
  { to: "/bids", label: "All Bids", icon: FileStack, end: false },
  { to: "/rejected", label: "Rejected", icon: MailX, end: false },
  { to: "/email-accounts", label: "Email Accounts", icon: Mail, end: false },
];

export function Sidebar() {
  return (
    <aside className="flex h-full w-16 flex-col border-r bg-card md:w-60">
      <div className="flex h-14 items-center gap-2 border-b px-4">
        <div className="flex size-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
          <Plane className="size-4" />
        </div>
        <span className="hidden text-base font-semibold md:inline">
          BidPilot
        </span>
      </div>
      <nav className="flex-1 space-y-1 p-2" aria-label="Primary">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
              )
            }
          >
            <Icon className="size-4 shrink-0" />
            <span className="hidden md:inline">{label}</span>
          </NavLink>
        ))}
      </nav>
      <div className="hidden border-t p-4 text-xs text-muted-foreground md:block">
        Construction bid comparison
      </div>
    </aside>
  );
}
