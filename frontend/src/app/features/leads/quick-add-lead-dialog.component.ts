import { CommonModule } from '@angular/common';
import { Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatChipsModule } from '@angular/material/chips';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatDividerModule } from '@angular/material/divider';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatRadioModule } from '@angular/material/radio';
import { MatSelectModule } from '@angular/material/select';
import { Router } from '@angular/router';
import { of } from 'rxjs';
import {
  catchError,
  debounceTime,
  distinctUntilChanged,
  filter,
  switchMap,
  tap,
} from 'rxjs/operators';
import { AuthService } from '../../core/auth/auth.service';
import {
  CheckPhoneOpenLead,
  CheckPhoneResponse,
  LeadCreatePayload,
  MANUAL_LEAD_SOURCES,
  PRODUCT_CATEGORIES,
} from '../../core/models/lead.model';
import { LeadService } from '../../core/services/lead.service';

@Component({
  selector: 'app-quick-add-lead-dialog',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatButtonModule,
    MatIconModule,
    MatCardModule,
    MatChipsModule,
    MatDividerModule,
    MatRadioModule,
    MatProgressSpinnerModule,
  ],
  template: `
    <div class="dialog-container">
      <div class="dialog-header">
        <h2 mat-dialog-title>
          <mat-icon color="primary">person_add</mat-icon>
          Quick Add Lead
        </h2>
        <button mat-icon-button mat-dialog-close aria-label="Close dialog">
          <mat-icon>close</mat-icon>
        </button>
      </div>

      <mat-dialog-content class="dialog-content">
        <form [formGroup]="leadForm" (ngSubmit)="onSubmit()">
          <!-- Section 1: Customer Phone (First field with duplicate detection) -->
          <div class="form-section">
            <h3 class="section-title">Customer Identification</h3>
            <mat-form-field appearance="outline" class="full-width">
              <mat-label>Customer Phone Number *</mat-label>
              <input
                matInput
                formControlName="customer_phone"
                placeholder="e.g. 9876543210 or +919876543210"
                autocomplete="tel"
              />
              <mat-icon matPrefix>phone</mat-icon>
              @if (isCheckingPhone()) {
                <mat-spinner matSuffix diameter="20"></mat-spinner>
              }
              <mat-error *ngIf="leadForm.get('customer_phone')?.hasError('required')">
                Phone number is required
              </mat-error>
              <mat-error *ngIf="leadForm.get('customer_phone')?.hasError('minlength')">
                Enter at least 10 digits
              </mat-error>
              <mat-error *ngIf="leadForm.get('customer_phone')?.hasError('serverError')">
                {{ leadForm.get('customer_phone')?.getError('serverError') }}
              </mat-error>
            </mat-form-field>

            <!-- Rate Limit Warning Card -->
            @if (rateLimitWarning()) {
              <div class="alert-box alert-warning">
                <mat-icon>warning</mat-icon>
                <span>{{ rateLimitWarning() }}</span>
              </div>
            }

            <!-- Existing Customer & Open Leads Card -->
            @if (phoneCheckResult() && phoneCheckResult()!.exists) {
              <mat-card class="duplicate-warning-card">
                <mat-card-header>
                  <mat-icon mat-card-avatar color="warn">person_search</mat-icon>
                  <mat-card-title>Existing Customer Recognized</mat-card-title>
                  <mat-card-subtitle>
                    {{ phoneCheckResult()!.customer?.name }}
                    @if (phoneCheckResult()!.customer?.company_name) {
                      ({{ phoneCheckResult()!.customer?.company_name }})
                    }
                  </mat-card-subtitle>
                </mat-card-header>

                <mat-card-content>
                  @if (authService.isManagerOrAdmin()) {
                    <div class="manager-customer-details">
                      <span *ngIf="phoneCheckResult()!.customer?.email">
                        <strong>Email:</strong> {{ phoneCheckResult()!.customer?.email }}
                      </span>
                      <span *ngIf="phoneCheckResult()!.customer?.total_spend">
                        <strong>Total Spend:</strong> ₹{{
                          phoneCheckResult()!.customer?.total_spend
                        }}
                      </span>
                    </div>
                  }

                  @if (openLeads().length > 0) {
                    <div class="open-leads-alert">
                      <p class="alert-title">
                        <mat-icon color="warn">priority_high</mat-icon>
                        <strong>Active Open Lead(s) Found ({{ openLeads().length }})</strong>
                      </p>
                      <div class="open-leads-list">
                        @for (openLead of openLeads(); track openLead.id) {
                          <div class="open-lead-row">
                            <div class="lead-info">
                              <span class="lead-title">{{
                                openLead.title || 'Untitled Lead'
                              }}</span>
                              <div class="lead-meta">
                                <span class="badge stage-badge">{{ openLead.stage_name }}</span>
                                <span class="badge assignee-badge">
                                  {{ openLead.assigned_to_name }}
                                  <span *ngIf="openLead.is_assigned_to_me">(You)</span>
                                </span>
                                <span *ngIf="openLead.deal_value" class="deal-value">
                                  ₹{{ openLead.deal_value }}
                                </span>
                              </div>
                            </div>
                            <button
                              type="button"
                              mat-stroked-button
                              color="primary"
                              (click)="openExistingLead(openLead.id)"
                            >
                              Open Lead #{{ openLead.id }}
                            </button>
                          </div>
                        }
                      </div>

                      <mat-divider></mat-divider>

                      <!-- Explicit Choice Mandatory if Open Leads Exist -->
                      <div class="explicit-choice-container">
                        <p class="choice-prompt">
                          <strong>Choose an action:</strong>
                        </p>
                        <mat-radio-group
                          [formControl]="duplicateActionControl"
                          class="duplicate-radio-group"
                        >
                          <mat-radio-button value="create_another">
                            Create another lead for this customer
                          </mat-radio-button>
                        </mat-radio-group>
                      </div>
                    </div>
                  }
                </mat-card-content>
              </mat-card>
            }
          </div>

          <!-- Section 2: Customer Details -->
          <div class="form-section">
            <h3 class="section-title">Customer Details</h3>
            <div class="form-row">
              <mat-form-field appearance="outline" class="half-width">
                <mat-label>Customer Name *</mat-label>
                <input matInput formControlName="customer_name" placeholder="Full name" />
                <mat-icon matPrefix>person</mat-icon>
                <mat-error *ngIf="leadForm.get('customer_name')?.hasError('required')">
                  Customer name is required
                </mat-error>
              </mat-form-field>

              <mat-form-field appearance="outline" class="half-width">
                <mat-label>Customer Email</mat-label>
                <input
                  matInput
                  type="email"
                  formControlName="customer_email"
                  placeholder="name@example.com"
                />
                <mat-icon matPrefix>email</mat-icon>
                <mat-error *ngIf="leadForm.get('customer_email')?.hasError('email')">
                  Enter a valid email
                </mat-error>
              </mat-form-field>
            </div>

            <div class="form-row">
              <mat-form-field appearance="outline" class="half-width">
                <mat-label>Customer Type</mat-label>
                <mat-select formControlName="customer_type">
                  <mat-option value="individual">Individual</mat-option>
                  <mat-option value="business">Business (B2B)</mat-option>
                </mat-select>
              </mat-form-field>

              <mat-form-field appearance="outline" class="half-width">
                <mat-label>Company Name</mat-label>
                <input matInput formControlName="company_name" placeholder="Organization name" />
              </mat-form-field>
            </div>
          </div>

          <!-- Section 3: Lead Details -->
          <div class="form-section">
            <h3 class="section-title">Lead Information</h3>

            <mat-form-field appearance="outline" class="full-width">
              <mat-label>Lead Title</mat-label>
              <input
                matInput
                formControlName="title"
                placeholder="e.g. Inquiring for gaming laptop"
              />
              <mat-icon matPrefix>title</mat-icon>
            </mat-form-field>

            <div class="form-row">
              <mat-form-field appearance="outline" class="half-width">
                <mat-label>Lead Source *</mat-label>
                <mat-select formControlName="source">
                  @for (source of leadSources; track source.value) {
                    <mat-option [value]="source.value">{{ source.label }}</mat-option>
                  }
                </mat-select>
              </mat-form-field>

              <mat-form-field appearance="outline" class="half-width">
                <mat-label>Product Category</mat-label>
                <mat-select formControlName="product_category">
                  @for (category of productCategories; track category.value) {
                    <mat-option [value]="category.value">{{ category.label }}</mat-option>
                  }
                </mat-select>
              </mat-form-field>
            </div>

            <div class="form-row">
              <mat-form-field appearance="outline" class="half-width">
                <mat-label>Preferred Brand</mat-label>
                <input matInput formControlName="product_brand" placeholder="e.g. Dell, HP, ASUS" />
              </mat-form-field>

              <div class="half-width budget-group">
                <mat-form-field appearance="outline" class="budget-field">
                  <mat-label>Min Budget (₹)</mat-label>
                  <input matInput type="number" formControlName="budget_min" placeholder="Min" />
                </mat-form-field>
                <mat-form-field appearance="outline" class="budget-field">
                  <mat-label>Max Budget (₹)</mat-label>
                  <input matInput type="number" formControlName="budget_max" placeholder="Max" />
                </mat-form-field>
              </div>
            </div>

            <mat-form-field appearance="outline" class="full-width">
              <mat-label>Requirement Notes</mat-label>
              <textarea
                matInput
                formControlName="notes"
                rows="3"
                placeholder="Specific customer requirements or specifications..."
              ></textarea>
            </mat-form-field>
          </div>

          <!-- Server Error Message Banner -->
          @if (serverErrorMessage()) {
            <div class="alert-box alert-error">
              <mat-icon>error</mat-icon>
              <span>{{ serverErrorMessage() }}</span>
            </div>
          }
        </form>
      </mat-dialog-content>

      <mat-dialog-actions align="end" class="dialog-actions">
        <button mat-button type="button" mat-dialog-close [disabled]="isSubmitting()">
          Cancel
        </button>
        <button
          mat-flat-button
          color="primary"
          type="button"
          (click)="onSubmit()"
          [disabled]="isSubmitDisabled()"
        >
          @if (isSubmitting()) {
            <mat-spinner diameter="18"></mat-spinner>
            <span>Creating...</span>
          } @else {
            <span>Create Lead</span>
          }
        </button>
      </mat-dialog-actions>
    </div>
  `,
  styles: [
    `
      .dialog-container {
        display: flex;
        flex-direction: column;
        max-height: 90vh;
      }

      .dialog-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 16px 24px;
        border-bottom: 1px solid #e2e8f0;

        h2 {
          display: flex;
          align-items: center;
          gap: 8px;
          margin: 0;
          font-size: 1.25rem;
          font-weight: 600;
        }
      }

      .dialog-content {
        padding: 16px 24px;
        overflow-y: auto;
      }

      .form-section {
        margin-bottom: 20px;
      }

      .section-title {
        font-size: 0.95rem;
        font-weight: 600;
        color: #475569;
        margin-bottom: 12px;
        text-transform: uppercase;
        letter-spacing: 0.05em;
      }

      .form-row {
        display: flex;
        gap: 16px;
        margin-bottom: 4px;
      }

      .half-width {
        flex: 1;
      }

      .full-width {
        width: 100%;
      }

      .budget-group {
        display: flex;
        gap: 8px;
      }

      .budget-field {
        flex: 1;
      }

      .alert-box {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 10px 14px;
        border-radius: 6px;
        font-size: 0.875rem;
        margin-bottom: 16px;

        &.alert-warning {
          background-color: #fffbeb;
          color: #b45309;
          border: 1px solid #fde68a;
        }

        &.alert-error {
          background-color: #fef2f2;
          color: #b91c1c;
          border: 1px solid #fecaca;
        }
      }

      .duplicate-warning-card {
        margin-bottom: 16px;
        background-color: #fffaf0;
        border: 1px solid #feebc8;

        mat-card-subtitle {
          color: #744210;
        }
      }

      .manager-customer-details {
        display: flex;
        gap: 16px;
        font-size: 0.85rem;
        color: #4a5568;
        margin-bottom: 12px;
      }

      .open-leads-alert {
        margin-top: 8px;

        .alert-title {
          display: flex;
          align-items: center;
          gap: 6px;
          color: #c53030;
          margin-bottom: 8px;
        }
      }

      .open-leads-list {
        display: flex;
        flex-direction: column;
        gap: 8px;
        margin-bottom: 12px;
      }

      .open-lead-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: #ffffff;
        padding: 8px 12px;
        border-radius: 6px;
        border: 1px solid #e2e8f0;

        .lead-title {
          font-weight: 500;
          font-size: 0.9rem;
        }

        .lead-meta {
          display: flex;
          gap: 6px;
          margin-top: 4px;
        }

        .badge {
          font-size: 0.75rem;
          padding: 2px 6px;
          border-radius: 4px;
        }

        .stage-badge {
          background-color: #e2e8f0;
          color: #1a202c;
        }

        .assignee-badge {
          background-color: #ebf8ff;
          color: #2b6cb0;
        }

        .deal-value {
          font-size: 0.8rem;
          color: #2f855a;
          font-weight: 600;
        }
      }

      .explicit-choice-container {
        margin-top: 12px;

        .choice-prompt {
          margin-bottom: 6px;
          font-size: 0.875rem;
        }

        .duplicate-radio-group {
          display: flex;
          flex-direction: column;
        }
      }

      .dialog-actions {
        padding: 12px 24px;
        border-top: 1px solid #e2e8f0;
        gap: 8px;
      }

      @media (max-width: 600px) {
        .form-row {
          flex-direction: column;
          gap: 0;
        }
        .half-width {
          width: 100%;
        }
        .open-lead-row {
          flex-direction: column;
          align-items: flex-start;
          gap: 8px;
        }
      }
    `,
  ],
})
export class QuickAddLeadDialogComponent implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly leadService = inject(LeadService);
  public readonly authService = inject(AuthService);
  private readonly router = inject(Router);
  private readonly dialogRef = inject(MatDialogRef<QuickAddLeadDialogComponent>);
  private readonly destroyRef = inject(DestroyRef);

  readonly leadSources = MANUAL_LEAD_SOURCES;
  readonly productCategories = PRODUCT_CATEGORIES;

  readonly isCheckingPhone = signal(false);
  readonly rateLimitWarning = signal<string | null>(null);
  readonly phoneCheckResult = signal<CheckPhoneResponse | null>(null);
  readonly openLeads = signal<CheckPhoneOpenLead[]>([]);
  readonly isSubmitting = signal(false);
  readonly serverErrorMessage = signal<string | null>(null);

  readonly duplicateActionControl = this.fb.control<string>('');

  leadForm: FormGroup = this.fb.group({
    customer_phone: ['', [Validators.required, Validators.minLength(10)]],
    customer_name: ['', Validators.required],
    customer_email: ['', [Validators.email]],
    customer_type: ['individual'],
    company_name: [''],
    gstin: [''],
    title: [''],
    source: ['walk_in', Validators.required],
    product_category: ['laptops'],
    product_brand: [''],
    budget_min: [null],
    budget_max: [null],
    notes: [''],
  });

  ngOnInit(): void {
    this.setupPhoneCheck();
  }

  private setupPhoneCheck(): void {
    const phoneControl = this.leadForm.get('customer_phone');
    if (!phoneControl) return;

    phoneControl.valueChanges
      .pipe(
        takeUntilDestroyed(this.destroyRef),
        debounceTime(400),
        distinctUntilChanged(),
        filter((phone: string | null): phone is string => {
          if (!phone || phone.trim().length < 6) {
            this.phoneCheckResult.set(null);
            this.openLeads.set([]);
            this.rateLimitWarning.set(null);
            this.duplicateActionControl.setValue('');
            return false;
          }
          return true;
        }),
        tap(() => {
          this.isCheckingPhone.set(true);
          this.rateLimitWarning.set(null);
        }),
        switchMap((phone: string) =>
          this.leadService.checkPhone(phone.trim()).pipe(
            catchError((err) => {
              this.isCheckingPhone.set(false);
              if (err && err.status === 429) {
                this.rateLimitWarning.set(
                  'Phone lookup is rate-limited. You can still fill in the details and submit.',
                );
              }
              return of(null);
            }),
          ),
        ),
      )
      .subscribe((res: CheckPhoneResponse | null) => {
        this.isCheckingPhone.set(false);
        if (!res) return;

        this.phoneCheckResult.set(res);
        this.openLeads.set(res.open_leads || []);

        if (res.exists && res.customer) {
          const nameControl = this.leadForm.get('customer_name');
          if (nameControl && !nameControl.value && res.customer.name) {
            nameControl.setValue(res.customer.name);
          }
          const emailControl = this.leadForm.get('customer_email');
          if (emailControl && !emailControl.value && res.customer.email) {
            emailControl.setValue(res.customer.email);
          }
          const companyControl = this.leadForm.get('company_name');
          if (companyControl && !companyControl.value && res.customer.company_name) {
            companyControl.setValue(res.customer.company_name);
          }
          const typeControl = this.leadForm.get('customer_type');
          if (typeControl && res.customer.customer_type) {
            typeControl.setValue(res.customer.customer_type);
          }
        }
      });
  }

  openExistingLead(leadId: number): void {
    this.dialogRef.close();
    this.router.navigate(['/leads', leadId]);
  }

  isSubmitDisabled(): boolean {
    if (this.leadForm.invalid || this.isSubmitting() || this.isCheckingPhone()) {
      return true;
    }

    // If active open leads exist, user must explicitly confirm creating another lead
    if (this.openLeads().length > 0 && this.duplicateActionControl.value !== 'create_another') {
      return true;
    }

    return false;
  }

  onSubmit(): void {
    if (this.isSubmitDisabled()) {
      this.leadForm.markAllAsTouched();
      return;
    }

    this.isSubmitting.set(true);
    this.serverErrorMessage.set(null);

    const val = this.leadForm.value;
    const payload: LeadCreatePayload = {
      customer_phone: val.customer_phone,
      customer_name: val.customer_name,
      customer_email: val.customer_email || undefined,
      customer_type: val.customer_type,
      company_name: val.company_name || undefined,
      gstin: val.gstin || undefined,
      title: val.title || undefined,
      source: val.source,
      product_category: val.product_category,
      product_brand: val.product_brand || undefined,
      budget_min: val.budget_min !== null && val.budget_min !== '' ? val.budget_min : null,
      budget_max: val.budget_max !== null && val.budget_max !== '' ? val.budget_max : null,
      notes: val.notes || undefined,
    };

    this.leadService.createLead(payload).subscribe({
      next: (res) => {
        this.isSubmitting.set(false);
        this.dialogRef.close({ created: true, lead: res.lead });
      },
      error: (err) => {
        this.isSubmitting.set(false);
        if (err && err.status === 400 && typeof err.error === 'object') {
          let hasFieldErrors = false;
          for (const key of Object.keys(err.error)) {
            const control = this.leadForm.get(key);
            if (control) {
              const messages = Array.isArray(err.error[key])
                ? err.error[key].join(' ')
                : String(err.error[key]);
              control.setErrors({ serverError: messages });
              hasFieldErrors = true;
            }
          }
          if (!hasFieldErrors) {
            this.serverErrorMessage.set(
              err.error.detail || 'Failed to create lead. Please check the inputs.',
            );
          }
        } else {
          this.serverErrorMessage.set(
            err.error?.detail || 'An unexpected error occurred while creating the lead.',
          );
        }
      },
    });
  }
}
