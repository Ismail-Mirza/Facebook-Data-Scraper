import axios from "axios";
import type { Ad, BackendInfo, JobSummary, ProxyEntry, SearchRequest } from "./types";

const baseURL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export const client = axios.create({ baseURL });

export async function getBackends(): Promise<BackendInfo[]> {
  const { data } = await client.get<BackendInfo[]>("/backends");
  return data;
}

export async function startSearch(req: SearchRequest): Promise<JobSummary> {
  const { data } = await client.post<JobSummary>("/search", req);
  return data;
}

export async function getJob(jobId: string): Promise<JobSummary> {
  const { data } = await client.get<JobSummary>(`/jobs/${jobId}`);
  return data;
}

export async function getResults(jobId: string): Promise<Ad[]> {
  const { data } = await client.get<Ad[]>(`/jobs/${jobId}/results?format=json`);
  return data;
}

export function resultsDownloadUrl(jobId: string, format: "csv" | "json"): string {
  return `${baseURL}/jobs/${jobId}/results?format=${format}`;
}

export async function getProxies(): Promise<{ current: ProxyEntry | null; working: ProxyEntry[] }> {
  const { data } = await client.get("/proxies");
  return data;
}

export async function refreshProxies(): Promise<{ count: number; working: ProxyEntry[] }> {
  const { data } = await client.post("/proxies/refresh");
  return data;
}

export async function rotateProxy(): Promise<{ current: ProxyEntry | null }> {
  const { data } = await client.post("/proxies/rotate");
  return data;
}
