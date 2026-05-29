import { ReactNode } from "react";
import { LucideIcon, Inbox } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * EmptyState — a centred, friendly placeholder for "no data yet" and error
 * surfaces. Accepts an optional icon, a title, supporting text, and an action
 * slot (e.g. a primary button to create the missing thing).
 */
export function EmptyState({
  icon: Icon = Inbox,
  title,
  description,
  action,
  className,
}: {
  icon?: LucideIcon;
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-lg border border-dashed bg-card/50 px-6 py-16 text-center",
        className
      )}
    >
      <div className="mb-4 flex size-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
        <Icon className="size-6" />
      </div>
      <h3 className="text-base font-semibold">{title}</h3>
      {description && (
        <p className="mt-1 max-w-sm text-sm text-muted-foreground">
          {description}
        </p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
