import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getProxies, refreshProxies, rotateProxy } from "../api";

export default function ProxyStatus() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["proxies"], queryFn: getProxies });

  const refresh = useMutation({
    mutationFn: refreshProxies,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["proxies"] }),
  });
  const rotate = useMutation({
    mutationFn: rotateProxy,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["proxies"] }),
  });

  const working = data?.working ?? [];
  const current = data?.current;

  return (
    <div className="rounded-lg bg-white shadow p-5 space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Proxy</h2>
        <span className="text-xs text-slate-500">{working.length} healthy</span>
      </div>

      <div className="rounded bg-slate-50 p-3 text-sm font-mono">
        {isLoading ? "loading…" : current ? `${current.host}:${current.port} (${current.country ?? "?"})` : "none"}
      </div>

      <div className="flex gap-2">
        <button
          onClick={() => refresh.mutate()}
          disabled={refresh.isPending}
          className="flex-1 rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-50"
        >
          {refresh.isPending ? "Refreshing…" : "Refresh list"}
        </button>
        <button
          onClick={() => rotate.mutate()}
          disabled={rotate.isPending || working.length === 0}
          className="flex-1 rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-50"
        >
          {rotate.isPending ? "Rotating…" : "Rotate"}
        </button>
      </div>

      <p className="text-xs text-slate-500">
        Webshare residential HTTP proxies. Health-checked against
        gstatic.com/generate_204.
      </p>
    </div>
  );
}
