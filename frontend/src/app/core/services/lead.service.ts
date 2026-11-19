import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import {
  CheckPhoneResponse,
  Lead,
  LeadCreatePayload,
  LeadFilterParams,
  PaginatedLeadList,
  Stage,
} from '../models/lead.model';
import { User } from '../models/user.model';

export interface LeadCreateResponse {
  lead: Lead;
  existing_customer: boolean;
  open_leads_warning: unknown[];
}

@Injectable({
  providedIn: 'root',
})
export class LeadService {
  private readonly http = inject(HttpClient);

  getLeads(filters: LeadFilterParams = {}): Observable<PaginatedLeadList> {
    let params = new HttpParams();

    if (filters.page) {
      params = params.set('page', filters.page.toString());
    }
    if (filters.page_size) {
      params = params.set('page_size', filters.page_size.toString());
    }
    if (filters.search) {
      params = params.set('search', filters.search);
    }
    if (filters.stage !== undefined && filters.stage !== '') {
      params = params.set('stage', filters.stage.toString());
    }
    if (filters.source) {
      params = params.set('source', filters.source);
    }
    if (filters.assigned_to !== undefined && filters.assigned_to !== '') {
      params = params.set('assigned_to', filters.assigned_to.toString());
    }
    if (filters.product_category) {
      params = params.set('product_category', filters.product_category);
    }
    if (filters.ordering) {
      params = params.set('ordering', filters.ordering);
    }

    return this.http.get<PaginatedLeadList>('/api/leads/', { params });
  }

  getStages(): Observable<Stage[]> {
    return this.http.get<Stage[]>('/api/leads/stages/');
  }

  checkPhone(phone: string): Observable<CheckPhoneResponse> {
    return this.http.post<CheckPhoneResponse>('/api/leads/check-phone/', { phone });
  }

  createLead(payload: LeadCreatePayload): Observable<LeadCreateResponse> {
    return this.http.post<LeadCreateResponse>('/api/leads/', payload);
  }

  getUsers(): Observable<User[]> {
    return this.http.get<User[]>('/api/users/');
  }
}
