export interface TripRequestPayload {
  destination: string;
  start_date: string;
  end_date: string;
  travelers: number;
  budget: number;
  preferences: string[];
  pace?: string | null;
  dietary_preferences: string[];
  hotel_level?: string | null;
  special_notes?: string | null;
  departure_city?: string | null;
  preferred_departure_period?: "上午" | "下午" | "晚上" | null;
  preferred_train_types: Array<"G" | "D" | "C" | "Z" | "T" | "K">;
  seat_preference?: "商务座" | "一等座" | "二等座" | "软卧" | "硬卧" | "硬座" | "无座" | null;
}

export type TripGenerationJobState =
  | "queued"
  | "running"
  | "cancelling"
  | "cancelled"
  | "completed"
  | "failed";

export interface TripGenerationJobCreated {
  job_id: string;
  status: "queued" | "running";
  reused: boolean;
}

export interface TripGenerationJobStatus {
  job_id: string;
  status: TripGenerationJobState;
  stage: string;
  progress: number;
  itinerary?: Itinerary | null;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
}

export interface TripEditPayload {
  trip_id: string;
  current_itinerary: Itinerary;
  user_instruction: string;
  edit_scope?: string | null;
  preserve_constraints: string[];
}

export interface SpotItem {
  name: string;
  start_time?: string | null;
  end_time?: string | null;
  description?: string | null;
  estimated_cost?: number;
  location?: string | null;
  image_url?: string | null;
  address?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  poi_id?: string | null;
}

export interface MealItem {
  name: string;
  meal_type: string;
  estimated_cost?: number;
  notes?: string | null;
}

export interface HotelItem {
  name: string;
  level?: string | null;
  estimated_cost?: number;
  location?: string | null;
  address?: string | null;
  latitude?: number | null;
  longitude?: number | null;
}

export interface TransportItem {
  mode: string;
  from_place?: string | null;
  to_place?: string | null;
  estimated_cost?: number;
  duration?: string | null;
  distance_km?: number | null;
  estimated_minutes?: number | null;
}

export interface DayPlan {
  day_index: number;
  date?: string | null;
  theme?: string | null;
  spots: SpotItem[];
  meals: MealItem[];
  hotel?: HotelItem | null;
  transport: TransportItem[];
  notes: string[];
}

export interface BudgetBreakdown {
  transport: number;
  hotel: number;
  meals: number;
  tickets: number;
  other: number;
  total: number;
}

export interface Itinerary {
  trip_id: string;
  destination: string;
  summary: string;
  days: DayPlan[];
  estimated_budget: number;
  budget_breakdown: BudgetBreakdown;
  tips: string[];
  source_notes: string[];
  provenance?: ItineraryProvenance;
  rail_tickets?: RailTicketPlan;
}

export interface RailTicketOption {
  train_code: string;
  travel_date: string;
  departure_station: string;
  arrival_station: string;
  departure_time: string;
  arrival_time: string;
  duration: string;
  duration_minutes?: number | null;
  seats: Record<string, string>;
  prices: Record<string, number>;
  preferred_seat?: string | null;
  preferred_seat_availability?: string | null;
  preferred_seat_price?: number | null;
}

export interface RailTicketPlan {
  status: "available" | "unavailable" | "error" | "disabled";
  departure_city?: string | null;
  destination?: string | null;
  outbound: RailTicketOption[];
  return_trip: RailTicketOption[];
  queried_at?: string | null;
  source_name: string;
  source_url: string;
  disclaimer: string;
  message?: string | null;
}

export interface ItineraryProvenance {
  planning_source: "llm_with_rag" | "llm_general_knowledge" | "rule_fallback" | "unknown";
  rag_status: "matched" | "unavailable" | "unknown";
  rag_context_count: number;
  map_status: "pending" | "verified" | "partial" | "unavailable" | "disabled" | "unknown";
  map_verified_spots: number;
  map_total_spots: number;
  rail_status: "available" | "unavailable" | "error" | "disabled" | "unknown";
  budget_is_estimate: boolean;
}

export interface TripSaveResponse {
  message: string;
  trip_id: string;
}

export interface TripSummaryItem {
  trip_id: string;
  destination: string;
  summary: string;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface TripListResponse {
  total: number;
  items: TripSummaryItem[];
}

export interface TripDetailResponse {
  trip_id: string;
  itinerary: Itinerary;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface WeatherForecastDay {
  date?: string | null;
  week?: string | null;
  day_weather?: string | null;
  night_weather?: string | null;
  day_temp?: string | null;
  night_temp?: string | null;
  day_wind?: string | null;
  night_wind?: string | null;
}

export interface WeatherForecastResponse {
  city: string;
  province?: string | null;
  adcode?: string | null;
  report_time?: string | null;
  days: WeatherForecastDay[];
}
