import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { FolderKanban, MapPin, ChevronRight, AlertCircle } from "lucide-react";
import { PageShell } from "@/components/layout/PageShell";
import { Card, CardContent } from "@/components/ui/card";
import { CardGridSkeleton } from "@/components/common/LoadingSkeleton";
import { EmptyState } from "@/components/common/EmptyState";
import { formatDate } from "@/lib/utils";
import { apiClient } from "@/api/client";

/**
 * ProjectsPage — lists every project as a card grid. Each card links into the
 * project detail view where jobs and their bids live.
 */
export function ProjectsPage() {
  const query = useQuery({
    queryKey: ["projects"],
    queryFn: () => apiClient.listProjects(),
  });

  return (
    <PageShell
      title="Projects"
      description="Every project bids have been matched to."
    >
      {query.isLoading ? (
        <CardGridSkeleton />
      ) : query.isError ? (
        <EmptyState
          icon={AlertCircle}
          title="Couldn't load projects"
          description="The project list failed to load. Try refreshing."
        />
      ) : !query.data || query.data.length === 0 ? (
        <EmptyState
          icon={FolderKanban}
          title="No projects yet"
          description="Projects are created automatically when bids arrive and get matched."
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {query.data.map((project) => (
            <Link
              key={project.id}
              to={`/projects/${encodeURIComponent(project.id)}`}
              className="block rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <Card className="h-full transition-shadow hover:shadow-md">
                <CardContent className="flex h-full flex-col gap-3 p-4">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className="flex size-8 items-center justify-center rounded-md bg-primary/10 text-primary">
                        <FolderKanban className="size-4" />
                      </span>
                      <h3 className="font-medium leading-tight">
                        {project.name}
                      </h3>
                    </div>
                    <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
                  </div>

                  {project.address && (
                    <p className="flex items-start gap-1.5 text-sm text-muted-foreground">
                      <MapPin className="mt-0.5 size-3.5 shrink-0" />
                      <span className="line-clamp-2">{project.address}</span>
                    </p>
                  )}

                  <div className="mt-auto flex items-center justify-between pt-1 text-xs text-muted-foreground">
                    {project.clientName && (
                      <span className="truncate">{project.clientName}</span>
                    )}
                    <span>{formatDate(project.createdAt)}</span>
                  </div>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </PageShell>
  );
}
