import { useState } from "react";
import SearchForm from "./components/SearchForm";
import JobProgress from "./components/JobProgress";
import ResultsTable from "./components/ResultsTable";
import ProxyStatus from "./components/ProxyStatus";

export default function App() {
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobDone, setJobDone] = useState(false);

  return (
    <div className="min-h-screen">
      <header className="bg-slate-900 text-white px-6 py-4 shadow">
        <h1 className="text-xl font-semibold">Meta Ads Library Scraper</h1>
        <p className="text-xs text-slate-300">
          Chrome (CDP) + Playwright dual-backend · GraphQL interception with DOM fallback
        </p>
      </header>

      <main className="mx-auto max-w-6xl p-6 grid gap-6 lg:grid-cols-[380px_1fr]">
        <section className="space-y-6">
          <SearchForm
            onJobStarted={(id) => {
              setJobId(id);
              setJobDone(false);
            }}
          />
          <ProxyStatus />
        </section>

        <section className="space-y-6">
          {jobId ? (
            <>
              <JobProgress jobId={jobId} onDone={() => setJobDone(true)} />
              {jobDone && <ResultsTable jobId={jobId} />}
            </>
          ) : (
            <div className="rounded-lg border border-dashed border-slate-300 p-12 text-center text-slate-500">
              Submit a search to see live progress and results here.
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
