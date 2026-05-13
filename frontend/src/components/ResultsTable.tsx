import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getResults, resultsDownloadUrl } from "../api";
import type { Ad } from "../types";

interface Props {
  jobId: string;
}

const PAGE_SIZE = 25;

export default function ResultsTable({ jobId }: Props) {
  const [page, setPage] = useState(0);
  const { data: ads = [], isLoading } = useQuery<Ad[]>({
    queryKey: ["results", jobId],
    queryFn: () => getResults(jobId),
  });

  const slice = useMemo(() => ads.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE), [ads, page]);
  const pages = Math.max(1, Math.ceil(ads.length / PAGE_SIZE));

  return (
    <div className="rounded-lg bg-white shadow">
      <div className="flex items-center justify-between p-4 border-b border-slate-200">
        <h2 className="text-lg font-semibold">Results ({ads.length})</h2>
        <div className="flex gap-2">
          <a
            href={resultsDownloadUrl(jobId, "csv")}
            className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50"
          >
            Download CSV
          </a>
          <a
            href={resultsDownloadUrl(jobId, "json")}
            className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50"
          >
            Download JSON
          </a>
        </div>
      </div>

      {isLoading ? (
        <p className="p-4 text-sm text-slate-500">Loading results…</p>
      ) : ads.length === 0 ? (
        <p className="p-4 text-sm text-slate-500">No ads captured.</p>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-3 py-2">Page</th>
                  <th className="px-3 py-2">Body</th>
                  <th className="px-3 py-2">CTA</th>
                  <th className="px-3 py-2">Platforms</th>
                  <th className="px-3 py-2">Started</th>
                  <th className="px-3 py-2">Media</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {slice.map((ad) => (
                  <tr key={ad.ad_archive_id}>
                    <td className="px-3 py-2 font-medium">{ad.page_name ?? "—"}</td>
                    <td className="px-3 py-2 max-w-md">
                      <span className="line-clamp-3 text-slate-700">
                        {ad.body_text ?? "—"}
                      </span>
                    </td>
                    <td className="px-3 py-2">{ad.cta_text ?? "—"}</td>
                    <td className="px-3 py-2 text-xs text-slate-500">
                      {ad.publisher_platforms.join(", ") || "—"}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {ad.start_date ? new Date(ad.start_date).toLocaleDateString() : "—"}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {ad.images.length}img / {ad.videos.length}vid
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between p-3 border-t border-slate-200 text-sm">
            <span className="text-slate-500">
              Page {page + 1} of {pages}
            </span>
            <div className="flex gap-2">
              <button
                disabled={page === 0}
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                className="rounded border border-slate-300 px-3 py-1 disabled:opacity-50"
              >
                Prev
              </button>
              <button
                disabled={page >= pages - 1}
                onClick={() => setPage((p) => Math.min(pages - 1, p + 1))}
                className="rounded border border-slate-300 px-3 py-1 disabled:opacity-50"
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
