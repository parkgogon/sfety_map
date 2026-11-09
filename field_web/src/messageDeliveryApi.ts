import type { NotificationPreview } from "./messageAnalysisApi";
export interface DeliveryStatus {
  deployment_enabled:boolean; can_activate:boolean; active:boolean; state:string; generation:string|null;
  started_at:string|null; detail:string; worker?:{at:string;revision:string;state:string}|null; worker_stale?:boolean;
}
export interface DeliveryItem {
  id?:string; record_id?:string|null; source_revision?:number; destination?:string; state?:string; detail?:string;
  preview_text?:string; created_at?:string; updated_at?:string; attempts?:number; message_id?:number|null;
  available_at?:string; resolved_at?:string|null; resolution?:string|null; source_count?:number;
  recent_record_ids?:string[]; decision?:{snapshot:NotificationPreview};
  can_reconsider?:boolean;
  delivery_state?:string|null;
}
export interface DeliveryPage {items:DeliveryItem[];next_cursor:string|null}
export type DeliveryKind = "deliveries"|"decisions"|"exceptions";
