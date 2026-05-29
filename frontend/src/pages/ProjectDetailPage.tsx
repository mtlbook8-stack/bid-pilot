import { useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  MapPin,
  GitCompareArrows,
  Hammer,
  AlertCircle,
  Loader2,
} from "lucide-react";
import { PageShell } from "@/components/layout/PageShell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { LoadingSkeleton } from "@/components/common/LoadingSkeleton";
import { EmptyState } from "@/components/common/EmptyState";
import { apiClient } from "@/api/client";
import { ApiError } from "@/api/client";
import type { JobSummary } from "@/types";

/**
 * ProjectDetailPage — a project's jobs, each with a Compare button that kicks
 * off the comparison pipeline (build doc 8.3) and routes to the resulting
 * session page. Compare is disabled when a job has fewer than two bids since
 * there's nothing to compare.
 */
export function ProjectDetailPage() {
  const { projectId = "" } = useParams();
  const projectQuery = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => apiClient.getProject(projectId),
    enabled: Boolean(projectId),
  });
  const jobsQuery = useQuery({
    queryKey: ["jobs", projectId],
    queryFn: () => apiClient.listProjectJobs(projectId),
    enabled: Boolean(projectId),
  });

  const project = projectQuery.data;

  return (
    <PageShell
      breadcrumb={
        <Link to="/projects" className="hover:text-foreground">
          ← Projects
        </Link>
      }
      title={project?.name ?? "Project"}
      description={project?.address ?? undefined}
    >
      {project?.client_name && (
        <p className="-mt-4 mb-4 flex items-center gap-1.5 text-sm text-muted-foreground">
          <MapPin className="size-3.5" /> Client: {project.client_name}
        </p>
      )}

      <h2 className="mb-3 text-base font-semibold">Jobs</h2>

      {jobsQuery.isLoading ? (
        <LoadingSkeleton lines={4} variant="card" />
      ) : jobsQuery.isError ? (
        <EmptyState
          icon={AlertCircle}
          title="Couldn't load jobs"
          description="The job list for this project failed to load."
        />
      ) : !jobsQuery.data || jobsQuery.data.length === 0 ? (
        <EmptyState
          icon={Hammer}
          title="No jobs yet"
          description="Jobs appear once bids for this project are categorized by trade."
        />
      ) : (
        <div className="space-y-3">
          {jobsQuery.data.map((job) => (
            <JobRow key={job.id} job={job} projectId={projectId} />
          ))}
        </div>
      )}
    </PageShell>
  );
}

function JobRow({ job, projectId }: { job: JobSummary; projectId: string }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  const bidCount = job.bid_ids.length;
  const canCompare = bidCount >= 2;

  const start = useMutation({
    mutationFn: () => apiClient.startComparison(projectId, job.id),
    onSuccess: (session) => {
      // Prime the cache so the session page renders instantly.
      queryClient.setQueryData(["session", projectId, session.id], session);
      navigate(
        `/projects/${encodeURIComponent(projectId)}/compare/${encodeURIComponent(
          session.id
        )}`
      );
    },
    onError: (err) => {
      setError(
        err instanceof ApiError
          ? err.message
          : "Failed to start the comparison. Try again."
      );
    },
  });

  return (
    <Card>
      <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="flex size-8 items-center justify-center rounded-md bg-muted text-muted-foreground">
              <Hammer className="size-4" />
            </span>
            <h3 className="truncate font-medium">{job.job_name}</h3>
          </div>
          <div className="mt-1.5 flex items-center gap-2">
            <Badge variant="outline">{job.trade_category}</Badge>
            <span className="text-sm text-muted-foreground">
              {bidCount} {bidCount === 1 ? "bid" : "bids"}
            </span>
          </div>
          {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
        </div>

        <Button
          onClick={() => {
            setError(null);
            start.mutate();
          }}
          disabled={!canCompare || start.isPending}
          title={
            canCompare
              ? "Start an interactive comparison"
              : "Need at least 2 bids to compare"
          }
        >
          {start.isPending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <GitCompareArrows className="size-4" />
          )}
          {start.isPending ? "Starting…" : "Compare"}
        </Button>
      </CardContent>
    </Card>
  );
}
