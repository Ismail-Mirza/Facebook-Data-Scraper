export type InputType = "keyword" | "page_url" | "slug";
export type BackendName = "chrome" | "playwright";
export type JobStatus = "queued" | "running" | "completed" | "failed";

export interface SearchRequest {
  input_type: InputType;
  value: string;
  country: string;
  ad_type: string;
  media_type?: string;
  max_pages: number;
  use_proxy: boolean;
  backend?: BackendName;
  headless?: boolean;
}

export interface JobSummary {
  job_id: string;
  status: JobStatus;
  ad_count: number;
  pages_scrolled: number;
  backend_used: string | null;
  started_at: string | null;
  finished_at: string | null;
  error?: string | null;
  request?: SearchRequest;
}

export interface Ad {
  ad_archive_id: string;
  page_id: string | null;
  page_name: string | null;
  start_date: string | null;
  end_date: string | null;
  is_active: boolean | null;
  publisher_platforms: string[];
  body_text: string | null;
  cta_text: string | null;
  cta_type: string | null;
  display_format: string | null;
  images: string[];
  videos: string[];
  landing_url: string | null;
  spend: Record<string, unknown> | null;
  impressions: Record<string, unknown> | null;
  currency: string | null;
  funded_by: string | null;
  eu_total_reach: number | null;
}

export interface BackendInfo {
  name: BackendName;
  available: boolean;
  healthy: boolean;
  supports_per_request_proxy: boolean;
}

export interface ProxyEntry {
  host: string;
  port: number;
  protocol: string;
  country: string | null;
  healthy: boolean | null;
  last_checked: string | null;
}
