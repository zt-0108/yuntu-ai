import axios from "axios";

import type {
  Itinerary,
  TripGenerationJobCreated,
  TripGenerationJobStatus,
  TripDetailResponse,
  TripEditPayload,
  TripListResponse,
  TripRequestPayload,
  TripSaveResponse,
  WeatherForecastResponse,
} from "../types";

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 120000,
});

export async function generateTrip(
  payload: TripRequestPayload,
  onProgress?: (job: TripGenerationJobStatus) => void,
  signal?: AbortSignal,
): Promise<Itinerary> {
  const created = await api.post<TripGenerationJobCreated>(
    "/trip/generate/jobs",
    payload,
    { signal },
  );
  const jobId = created.data.job_id;
  const deadline = Date.now() + 300000;

  try {
    while (Date.now() < deadline) {
      if (signal?.aborted) {
        throw new DOMException("行程生成已取消。", "AbortError");
      }

      const response = await api.get<TripGenerationJobStatus>(
        `/trip/generate/jobs/${encodeURIComponent(jobId)}`,
        { signal },
      );
      const job = response.data;
      onProgress?.(job);

      if (job.status === "completed") {
        if (!job.itinerary) throw new Error("生成任务已完成，但没有返回行程数据。");
        return job.itinerary;
      }
      if (job.status === "failed") {
        throw new Error(job.error_message || "行程生成失败，请稍后重试。");
      }
      if (job.status === "cancelled") {
        throw new DOMException("行程生成已取消。", "AbortError");
      }

      await new Promise((resolve) => window.setTimeout(resolve, 1000));
    }

    throw new Error("行程生成超时，请稍后重试。");
  } catch (error) {
    if (signal?.aborted) {
      await api.delete(`/trip/generate/jobs/${encodeURIComponent(jobId)}`, {
        timeout: 10000,
      }).catch(() => undefined);
      throw new DOMException("行程生成已取消。", "AbortError");
    }
    throw error;
  }
}

export async function editTrip(payload: TripEditPayload): Promise<Itinerary> {
  const response = await api.post<Itinerary>("/trip/edit", payload, {
    timeout: 300000, // 5 分钟：单日编辑也需要LLM调用
  });
  return response.data;
}

export async function saveTrip(itinerary: Itinerary): Promise<TripSaveResponse> {
  const response = await api.post<TripSaveResponse>("/trip/save", {
    trip_id: itinerary.trip_id,
    itinerary,
    user_id: "yuntu_web_user",
  });
  return response.data;
}

export async function listTrips(): Promise<TripListResponse> {
  const response = await api.get<TripListResponse>("/trip");
  return response.data;
}

export async function getTripDetail(tripId: string): Promise<TripDetailResponse> {
  const response = await api.get<TripDetailResponse>(`/trip/${tripId}`);
  return response.data;
}

export async function deleteTrip(tripId: string): Promise<void> {
  await api.delete(`/trip/${tripId}`);
}

export async function fetchWeatherForecast(city: string): Promise<WeatherForecastResponse> {
  const response = await api.get<WeatherForecastResponse>("/weather/forecast", {
    params: { city },
  });
  return response.data;
}

export function getMarkdownExportUrl(tripId: string): string {
  return `${API_BASE_URL}/export/${encodeURIComponent(tripId)}/markdown`;
}

export function getPdfExportUrl(tripId: string): string {
  return `${API_BASE_URL}/export/${encodeURIComponent(tripId)}/pdf`;
}

export default api;
