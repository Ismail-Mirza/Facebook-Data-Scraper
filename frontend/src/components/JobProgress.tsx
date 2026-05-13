import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { getJob } from "../api";
import type { JobStatus } from "../types";

const STATUS_COLOR: Record<JobStatus, string> = {
  queued: "bg-slate-200 text-slate-700",
  running: "bg-blue-100 text-blue-700",
  completed: "bg-emerald-100 text-emerald-700",
  failed: "bg-red-100 text-red-700",
};

interface Props {
  jobId: string;
  onDone: () => void;
}

export default function JobProgress({ jobId, onDone }: Props) {
  const query = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => getJob(jobId),
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "completed" || s === "failed" ? false : 2000;
    },
  });

  const status = query.data?.status;
  useEffect(() => {
    if (status === "completed") onDone();
  }, [status, onDone]);

  if (!query.data) return <div className="rounded-lg bg-white p-5 shadow">Loading job…</div>;
  const j = query.data;

  return (
    <div className="rounded-lg bg-white p-5 shadow">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Job {j.job_id}</h2>
          <p className="text-xs text-slate-500">backend: {j.backend_used ?? "—"}</p>
        </div>
        <span className={`rounded px-2 py-1 text-xs font-medium ${STATUS_COLOR[j.status]}`}>
          {j.status}
        </span>
      </div>

      <dl className="mt-4 grid grid-cols-3 gap-4 text-sm">
        <div>
          <dt className="text-slate-500">Ads collected</dt>
          <dd className="text-2xl font-semibold">{j.ad_count}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Scroll rounds</dt>
          <dd className="text-2xl font-semibold">{j.pages_scrolled}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Started</dt>
          <dd className="text-xs">{j.started_at ? new Date(j.started_at).toLocaleTimeString() : "—"}</dd>
        </div>
      </dl>

      {j.error && (
        <pre className="mt-4 rounded bg-red-50 p-3 text-xs text-red-700 overflow-x-auto">
          {j.error}
        </pre>
      )}
    </div>
  );
}
