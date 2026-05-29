import { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * PageShell — the standard page frame: an optional breadcrumb/back slot, a
 * title + description block, an actions slot (right-aligned), and the page body.
 * Pages that need the full viewport (the comparison page) can opt out of the
 * default max-width via `fullBleed`.
 */
export function PageShell({
  title,
  description,
  actions,
  breadcrumb,
  children,
  fullBleed = false,
  className,
}: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  breadcrumb?: ReactNode;
  children: ReactNode;
  fullBleed?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex h-full flex-col overflow-hidden",
        fullBleed ? "" : "overflow-y-auto"
      )}
    >
      <div
        className={cn(
          "flex w-full flex-1 flex-col",
          fullBleed ? "min-h-0" : "mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8",
          className
        )}
      >
        {(title || actions || breadcrumb) && (
          <div className={cn(fullBleed && "px-4 py-4 sm:px-6")}>
            {breadcrumb && (
              <div className="mb-2 text-sm text-muted-foreground">
                {breadcrumb}
              </div>
            )}
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div>
                {title && (
                  <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">
                    {title}
                  </h1>
                )}
                {description && (
                  <p className="mt-1 text-sm text-muted-foreground">
                    {description}
                  </p>
                )}
              </div>
              {actions && (
                <div className="flex shrink-0 items-center gap-2">{actions}</div>
              )}
            </div>
          </div>
        )}
        <div className={cn("min-h-0 flex-1", !fullBleed && "mt-6")}>
          {children}
        </div>
      </div>
    </div>
  );
}
