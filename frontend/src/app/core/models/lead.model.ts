import { components } from '../api/schema';

export type Lead = components['schemas']['Lead'];
export type Stage = components['schemas']['Stage'];
export type PaginatedLeadList = components['schemas']['PaginatedLeadList'];

export interface CheckPhoneCustomer {
  id: number;
  name: string;
  phone?: string;
  email?: string;
  company_name?: string;
  customer_type?: string;
  total_spend?: string;
  open_leads_count?: number;
}

export interface CheckPhoneOpenLead {
  id: number;
  title?: string;
  stage_id?: number;
  stage_name: string;
  assigned_to_id?: number | null;
  assigned_to_name: string;
  is_assigned_to_me: boolean;
  deal_value?: string | null;
  created_at?: string;
}

export interface CheckPhoneResponse {
  exists: boolean;
  customer: CheckPhoneCustomer | null;
  open_leads: CheckPhoneOpenLead[];
}

export interface LeadCreatePayload {
  customer_name: string;
  customer_phone: string;
  customer_email?: string;
  customer_alt_phone?: string;
  customer_address?: string;
  customer_type?: 'individual' | 'business';
  company_name?: string;
  gstin?: string;
  customer_notes?: string;

  title?: string;
  source?: 'walk_in' | 'phone' | 'whatsapp' | 'website';
  product_category?:
    | 'laptops'
    | 'desktops'
    | 'cctv'
    | 'accessories'
    | 'repairs'
    | 'custom_pc'
    | 'networking'
    | 'printers_toners'
    | 'software'
    | 'other';
  product_brand?: string;
  budget_min?: number | string | null;
  budget_max?: number | string | null;
  notes?: string;
  assigned_to_id?: number | null;
}

export interface LeadFilterParams {
  page?: number;
  page_size?: number;
  search?: string;
  stage?: string | number;
  source?: string;
  assigned_to?: string | number;
  product_category?: string;
  ordering?: string;
}

export const MANUAL_LEAD_SOURCES = [
  { value: 'walk_in', label: 'Walk-in' },
  { value: 'phone', label: 'Phone Call' },
  { value: 'whatsapp', label: 'WhatsApp' },
  { value: 'website', label: 'Website' },
] as const;

export const PRODUCT_CATEGORIES = [
  { value: 'laptops', label: 'Laptops' },
  { value: 'desktops', label: 'Desktops' },
  { value: 'cctv', label: 'CCTV' },
  { value: 'accessories', label: 'Accessories' },
  { value: 'repairs', label: 'Repairs & Services' },
  { value: 'custom_pc', label: 'Custom PC' },
  { value: 'networking', label: 'Networking' },
  { value: 'printers_toners', label: 'Printers & Toners' },
  { value: 'software', label: 'Software' },
  { value: 'other', label: 'Other' },
] as const;
