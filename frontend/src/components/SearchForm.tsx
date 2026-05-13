import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { getBackends, startSearch } from "../api";
import type { BackendName, InputType } from "../types";

interface Props {
  onJobStarted: (jobId: string) => void;
}

const COUNTRIES = ["ALL", "US", "GB", "DE", "FR", "ES", "IT", "BR", "IN", "CA", "AU"];
const AD_TYPES = [
  { value: "all", label: "All ads" },
  { value: "political_and_issue_ads", label: "Political / issue ads" },
  { value: "housing_ads", label: "Housing" },
  { value: "employment_ads", label: "Employment" },
  { value: "credit_ads", label: "Credit" },
];

export default function SearchForm({ onJobStarted }: Props) {
  const [inputType, setInputType] = useState<InputType>("keyword");
  const [value, setValue] = useState("");
  const [country, setCountry] = useState("ALL");
  const [adType, setAdType] = useState("all");
  const [maxPages, setMaxPages] = useState(30);
  const [useProxy, setUseProxy] = useState(false);
  const [backend, setBackend] = useState<BackendName | "">("");
  const [showBrowser, setShowBrowser] = useState(true);

  const backendsQuery = useQuery({ queryKey: ["backends"], queryFn: getBackends });

  const mutation = useMutation({
    mutationFn: startSearch,
    onSuccess: (job) => onJobStarted(job.job_id),
  });

  const placeholder =
    inputType === "keyword"
      ? "e.g. solar panels"
      : inputType === "page_url"
      ? "https://www.facebook.com/Nike/"
      : "Nike  (or numeric page_id)";

  return (
    <form
      className="rounded-lg bg-white shadow p-5 space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (!value.trim()) return;
        mutation.mutate({
          input_type: inputType,
          value: value.trim(),
          country,
          ad_type: adType,
          max_pages: maxPages,
          use_proxy: useProxy,
          backend: backend || undefined,
          headless: backend === "playwright" ? !showBrowser : undefined,
        });
      }}
    >
      <h2 className="text-lg font-semibold">New search</h2>

      <fieldset>
        <legend className="text-sm font-medium mb-2">Search by</legend>
        <div className="flex gap-2 text-sm">
          {(["keyword", "page_url", "slug"] as InputType[]).map((opt) => (
            <label
              key={opt}
              className={`flex-1 cursor-pointer rounded border px-3 py-1.5 text-center ${
                inputType === opt
                  ? "border-slate-900 bg-slate-900 text-white"
                  : "border-slate-300 bg-white"
              }`}
            >
              <input
                type="radio"
                name="inputType"
                value={opt}
                checked={inputType === opt}
                onChange={() => setInputType(opt)}
                className="sr-only"
              />
              {opt === "page_url" ? "Page URL" : opt[0].toUpperCase() + opt.slice(1)}
            </label>
          ))}
        </div>
      </fieldset>

      <label className="block text-sm">
        <span className="font-medium">Query</span>
        <input
          className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
          placeholder={placeholder}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          required
        />
      </label>

      <div className="grid grid-cols-2 gap-3 text-sm">
        <label className="block">
          <span className="font-medium">Country</span>
          <select
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
            value={country}
            onChange={(e) => setCountry(e.target.value)}
          >
            {COUNTRIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="font-medium">Ad type</span>
          <select
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
            value={adType}
            onChange={(e) => setAdType(e.target.value)}
          >
            {AD_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="font-medium">Max scroll rounds</span>
          <input
            type="number"
            min={1}
            max={500}
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
            value={maxPages}
            onChange={(e) => setMaxPages(Number(e.target.value))}
          />
        </label>

        <label className="block">
          <span className="font-medium">Backend</span>
          <select
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
            value={backend}
            onChange={(e) => setBackend(e.target.value as BackendName | "")}
          >
            <option value="">Default</option>
            {backendsQuery.data?.map((b) => (
              <option key={b.name} value={b.name} disabled={!b.available}>
                {b.name} {b.healthy ? "✓" : "·"}
                {!b.available ? " (unavailable)" : ""}
              </option>
            ))}
          </select>
        </label>
      </div>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={useProxy}
          onChange={(e) => setUseProxy(e.target.checked)}
        />
        Route through rotating residential proxy
      </label>

      <label
        className={`flex items-center gap-2 text-sm ${
          backend === "playwright" ? "" : "opacity-50"
        }`}
        title={
          backend === "playwright"
            ? "Open a visible Chromium window so you can watch the scraper work"
            : "Visible browser is only available with the Playwright backend"
        }
      >
        <input
          type="checkbox"
          checked={showBrowser}
          onChange={(e) => setShowBrowser(e.target.checked)}
          disabled={backend !== "playwright"}
        />
        Show browser window (Playwright only — requires a display)
      </label>

      <button
        type="submit"
        disabled={mutation.isPending}
        className="w-full rounded bg-slate-900 px-4 py-2 text-white hover:bg-slate-700 disabled:opacity-50"
      >
        {mutation.isPending ? "Submitting…" : "Start search"}
      </button>

      {mutation.error && (
        <p className="text-sm text-red-600">
          {(mutation.error as Error).message}
        </p>
      )}
    </form>
  );
}
