import { CommonModule } from '@angular/common';
import { Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { MatBadgeModule } from '@angular/material/badge';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatChipsModule } from '@angular/material/chips';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSelectModule } from '@angular/material/select';
import { MatTableModule } from '@angular/material/table';
import { Router } from '@angular/router';
import { debounceTime, distinctUntilChanged } from 'rxjs/operators';
import { AuthService } from '../../core/auth/auth.service';
import { Lead, LeadFilterParams, PaginatedLeadList, Stage } from '../../core/models/lead.model';
import { User } from '../../core/models/user.model';
import { InrCurrencyPipe } from '../../core/pipes/inr-currency.pipe';
import { KolkataDatePipe } from '../../core/pipes/kolkata-date.pipe';
import { LeadService } from '../../core/services/lead.service';
import { QuickAddLeadDialogComponent } from './quick-add-lead-dialog.component';

@Component({
  selector: 'app-lead-list',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatTableModule,
    MatPaginatorModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatButtonModule,
    MatIconModule,
    MatCardModule,
    MatChipsModule,
    MatBadgeModule,
    MatProgressSpinnerModule,
    MatDialogModule,
    InrCurrencyPipe,
    KolkataDatePipe,
  ],
  template: `
    <div class="lead-list-container">
      <!-- Top Action Bar -->
      <div class="header-action-bar">
        <div class="title-group">
          <h1 class="page-title">Sales Leads</h1>
          <span class="lead-count-badge" *ngIf="!isLoading()"> {{ totalCount() }} total </span>
        </div>
        <button
          mat-flat-button
          color="primary"
          class="quick-add-btn"
          (click)="openQuickAddDialog()"
        >
          <mat-icon>add</mat-icon>
          Quick Add Lead
        </button>
      </div>

      <!-- Filters & Search Toolbar -->
      <mat-card class="filter-card">
        <div class="filter-row">
          <!-- Search box -->
          <mat-form-field appearance="outline" class="search-field">
            <mat-label>Search leads & customers</mat-label>
            <input matInput [formControl]="searchControl" placeholder="Name, phone, or title..." />
            <mat-icon matPrefix>search</mat-icon>
            <button
              mat-icon-button
              matSuffix
              *ngIf="searchControl.value"
              (click)="searchControl.setValue('')"
              aria-label="Clear search"
            >
              <mat-icon>close</mat-icon>
            </button>
          </mat-form-field>

          <!-- Stage Filter -->
          <mat-form-field appearance="outline" class="filter-select">
            <mat-label>Stage</mat-label>
            <mat-select [formControl]="stageFilterControl">
              <mat-option value="">All Stages</mat-option>
              @for (stg of stages(); track stg.id) {
                <mat-option [value]="stg.id">{{ stg.name }}</mat-option>
              }
            </mat-select>
          </mat-form-field>

          <!-- Source Filter -->
          <mat-form-field appearance="outline" class="filter-select">
            <mat-label>Source</mat-label>
            <mat-select [formControl]="sourceFilterControl">
              <mat-option value="">All Sources</mat-option>
              <mat-option value="walk_in">Walk-in</mat-option>
              <mat-option value="phone">Phone</mat-option>
              <mat-option value="whatsapp">WhatsApp</mat-option>
              <mat-option value="website">Website</mat-option>
              <mat-option value="meta_lead_ads">Meta Lead Ads</mat-option>
            </mat-select>
          </mat-form-field>

          <!-- Assignee Filter (Managers & Admins only) -->
          @if (authService.isManagerOrAdmin()) {
            <mat-form-field appearance="outline" class="filter-select">
              <mat-label>Assignee</mat-label>
              <mat-select [formControl]="assigneeFilterControl">
                <mat-option value="">All Assignees</mat-option>
                <mat-option value="unassigned">Unassigned Only</mat-option>
                @for (u of staffUsers(); track u.id) {
                  <mat-option [value]="u.id">{{ u.username }}</mat-option>
                }
              </mat-select>
            </mat-form-field>
          }

          <!-- Ordering Sort Filter -->
          <mat-form-field appearance="outline" class="filter-select">
            <mat-label>Sort By</mat-label>
            <mat-select [formControl]="orderingControl">
              <mat-option value="-created_at">Newest First</mat-option>
              <mat-option value="created_at">Oldest First</mat-option>
              <mat-option value="-last_activity_at">Recently Active</mat-option>
              <mat-option value="-deal_value">Deal Value: High to Low</mat-option>
              <mat-option value="deal_value">Deal Value: Low to High</mat-option>
              <mat-option value="-budget_min">Budget: High to Low</mat-option>
            </mat-select>
          </mat-form-field>
        </div>
      </mat-card>

      <!-- Loading State -->
      @if (isLoading()) {
        <div class="loading-state">
          <mat-spinner diameter="40"></mat-spinner>
          <span>Loading leads...</span>
        </div>
      }

      <!-- Error State -->
      @if (errorMessage()) {
        <div class="error-banner">
          <mat-icon color="warn">error_outline</mat-icon>
          <span>{{ errorMessage() }}</span>
          <button mat-stroked-button color="warn" (click)="loadLeads()">Retry</button>
        </div>
      }

      <!-- Empty State -->
      @if (!isLoading() && !errorMessage() && leads().length === 0) {
        <div class="empty-state">
          <mat-icon class="empty-icon">inbox</mat-icon>
          <h3>No leads found</h3>
          <p>Try adjusting your search filters or add a new sales lead.</p>
          <button mat-flat-button color="primary" (click)="openQuickAddDialog()">
            <mat-icon>add</mat-icon>
            Add First Lead
          </button>
        </div>
      }

      <!-- Desktop Table View -->
      @if (!isLoading() && !errorMessage() && leads().length > 0) {
        <div class="table-container desktop-only">
          <table mat-table [dataSource]="leads()" class="leads-table mat-elevation-z1">
            <!-- ID Column -->
            <ng-container matColumnDef="id">
              <th mat-header-cell *matHeaderCellDef>#ID</th>
              <td mat-cell *matCellDef="let lead">#{{ lead.id }}</td>
            </ng-container>

            <!-- Customer Column -->
            <ng-container matColumnDef="customer">
              <th mat-header-cell *matHeaderCellDef>Customer</th>
              <td mat-cell *matCellDef="let lead">
                <div class="customer-cell">
                  <span class="customer-name">{{ lead.customer_name }}</span>
                  <span class="customer-phone">{{ lead.customer_phone }}</span>
                </div>
              </td>
            </ng-container>

            <!-- Title & Product Column -->
            <ng-container matColumnDef="title">
              <th mat-header-cell *matHeaderCellDef>Title & Category</th>
              <td mat-cell *matCellDef="let lead">
                <div class="title-cell">
                  <span class="lead-title-text">{{ lead.title || 'Untitled' }}</span>
                  <div class="product-tags">
                    <span class="category-chip" *ngIf="lead.product_category">
                      {{ lead.product_category }}
                    </span>
                    <span class="brand-chip" *ngIf="lead.product_brand">
                      {{ lead.product_brand }}
                    </span>
                  </div>
                </div>
              </td>
            </ng-container>

            <!-- Stage Column -->
            <ng-container matColumnDef="stage">
              <th mat-header-cell *matHeaderCellDef>Stage</th>
              <td mat-cell *matCellDef="let lead">
                <span class="stage-pill" [ngClass]="'stage-' + lead.stage_slug">
                  {{ lead.stage_name }}
                </span>
              </td>
            </ng-container>

            <!-- Assignee Column -->
            <ng-container matColumnDef="assigned_to">
              <th mat-header-cell *matHeaderCellDef>Assignee</th>
              <td mat-cell *matCellDef="let lead">
                <span class="assignee-text">
                  {{ lead.assigned_to_name || 'Unassigned' }}
                </span>
              </td>
            </ng-container>

            <!-- Deal Value / Budget Column -->
            <ng-container matColumnDef="value">
              <th mat-header-cell *matHeaderCellDef>Value / Budget</th>
              <td mat-cell *matCellDef="let lead">
                <div class="value-cell">
                  @if (lead.deal_value) {
                    <span class="deal-value-text">{{ lead.deal_value | inrCurrency }}</span>
                  } @else if (lead.budget_min || lead.budget_max) {
                    <span class="budget-text">
                      {{ lead.budget_min | inrCurrency }} - {{ lead.budget_max | inrCurrency }}
                    </span>
                  } @else {
                    <span class="no-value">—</span>
                  }
                </div>
              </td>
            </ng-container>

            <!-- Created At Column -->
            <ng-container matColumnDef="created_at">
              <th mat-header-cell *matHeaderCellDef>Created</th>
              <td mat-cell *matCellDef="let lead">
                <span class="date-text">{{ lead.created_at | kolkataDate }}</span>
              </td>
            </ng-container>

            <!-- Actions Column -->
            <ng-container matColumnDef="actions">
              <th mat-header-cell *matHeaderCellDef>Action</th>
              <td mat-cell *matCellDef="let lead">
                <button
                  mat-icon-button
                  color="primary"
                  (click)="onRowClick(lead.id)"
                  matTooltip="View lead details"
                >
                  <mat-icon>chevron_right</mat-icon>
                </button>
              </td>
            </ng-container>

            <tr mat-header-row *matHeaderRowDef="displayedColumns"></tr>
            <tr
              mat-row
              *matRowDef="let row; columns: displayedColumns"
              class="clickable-row"
              (click)="onRowClick(row.id)"
            ></tr>
          </table>
        </div>

        <!-- Mobile Card View -->
        <div class="mobile-card-list mobile-only">
          @for (lead of leads(); track lead.id) {
            <mat-card class="mobile-lead-card" (click)="onRowClick(lead.id)">
              <div class="card-header-row">
                <span class="card-lead-id">#{{ lead.id }}</span>
                <span class="stage-pill" [ngClass]="'stage-' + lead.stage_slug">
                  {{ lead.stage_name }}
                </span>
              </div>
              <h4 class="card-customer-name">{{ lead.customer_name }}</h4>
              <p class="card-lead-title">{{ lead.title || 'Untitled Lead' }}</p>
              <div class="card-meta-row">
                <span class="card-phone">{{ lead.customer_phone }}</span>
                <span class="card-value" *ngIf="lead.deal_value">
                  {{ lead.deal_value | inrCurrency }}
                </span>
              </div>
              <div class="card-footer-row">
                <span class="card-assignee">
                  <mat-icon class="tiny-icon">person</mat-icon>
                  {{ lead.assigned_to_name || 'Unassigned' }}
                </span>
                <span class="card-date">{{ lead.created_at | kolkataDate }}</span>
              </div>
            </mat-card>
          }
        </div>

        <!-- Paginator -->
        <mat-paginator
          [length]="totalCount()"
          [pageSize]="pageSize()"
          [pageIndex]="pageIndex()"
          [pageSizeOptions]="[10, 20, 50]"
          (page)="onPageChange($event)"
          aria-label="Select lead page"
          class="mat-elevation-z1"
        ></mat-paginator>
      }
    </div>
  `,
  styles: [
    `
      .lead-list-container {
        padding: 24px;
        max-width: 1400px;
        margin: 0 auto;
      }

      .header-action-bar {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 20px;

        .title-group {
          display: flex;
          align-items: baseline;
          gap: 12px;

          .page-title {
            font-size: 1.75rem;
            font-weight: 700;
            color: #0f172a;
            margin: 0;
          }

          .lead-count-badge {
            font-size: 0.875rem;
            color: #64748b;
            font-weight: 500;
          }
        }
      }

      .filter-card {
        padding: 16px;
        margin-bottom: 20px;
        background-color: #ffffff;
      }

      .filter-row {
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        align-items: center;

        .search-field {
          flex: 2;
          min-width: 240px;
        }

        .filter-select {
          flex: 1;
          min-width: 140px;
        }
      }

      .loading-state,
      .empty-state {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 60px 20px;
        background: #ffffff;
        border-radius: 8px;
        color: #64748b;
        gap: 12px;
      }

      .empty-state {
        .empty-icon {
          font-size: 48px;
          height: 48px;
          width: 48px;
          color: #94a3b8;
        }

        h3 {
          margin: 0;
          font-size: 1.25rem;
          color: #1e293b;
        }

        p {
          margin: 0 0 8px 0;
        }
      }

      .error-banner {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 12px 16px;
        background-color: #fef2f2;
        border: 1px solid #fecaca;
        border-radius: 8px;
        color: #991b1b;
        margin-bottom: 20px;
      }

      .table-container {
        border-radius: 8px;
        overflow: hidden;
        margin-bottom: 16px;
      }

      .leads-table {
        width: 100%;

        .clickable-row {
          cursor: pointer;
          transition: background-color 0.15s ease;

          &:hover {
            background-color: #f1f5f9;
          }
        }

        .customer-cell {
          display: flex;
          flex-direction: column;

          .customer-name {
            font-weight: 600;
            color: #0f172a;
          }

          .customer-phone {
            font-size: 0.8rem;
            color: #64748b;
          }
        }

        .title-cell {
          display: flex;
          flex-direction: column;
          gap: 4px;

          .lead-title-text {
            font-weight: 500;
            color: #334155;
          }

          .product-tags {
            display: flex;
            gap: 4px;

            .category-chip,
            .brand-chip {
              font-size: 0.7rem;
              padding: 1px 6px;
              border-radius: 4px;
              background-color: #f1f5f9;
              color: #475569;
            }
          }
        }

        .value-cell {
          .deal-value-text {
            font-weight: 600;
            color: #15803d;
          }

          .budget-text {
            font-size: 0.85rem;
            color: #64748b;
          }

          .no-value {
            color: #cbd5e1;
          }
        }

        .date-text {
          font-size: 0.8rem;
          color: #64748b;
        }
      }

      .stage-pill {
        display: inline-block;
        font-size: 0.75rem;
        font-weight: 600;
        padding: 3px 8px;
        border-radius: 12px;
        background-color: #e2e8f0;
        color: #334155;

        &.stage-new {
          background-color: #dbeafe;
          color: #1d4ed8;
        }

        &.stage-contacted {
          background-color: #fef3c7;
          color: #b45309;
        }

        &.stage-qualifying {
          background-color: #e0e7ff;
          color: #4338ca;
        }

        &.stage-quoted {
          background-color: #ede9fe;
          color: #6d28d9;
        }

        &.stage-won {
          background-color: #dcfce7;
          color: #15803d;
        }

        &.stage-lost {
          background-color: #fee2e2;
          color: #b91c1c;
        }
      }

      /* Mobile Card View */
      .mobile-card-list {
        display: flex;
        flex-direction: column;
        gap: 12px;
        margin-bottom: 16px;
      }

      .mobile-lead-card {
        padding: 14px;
        border-radius: 8px;
        cursor: pointer;

        .card-header-row {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 6px;

          .card-lead-id {
            font-size: 0.8rem;
            color: #94a3b8;
            font-weight: 600;
          }
        }

        .card-customer-name {
          margin: 0 0 4px 0;
          font-size: 1rem;
          font-weight: 600;
          color: #0f172a;
        }

        .card-lead-title {
          margin: 0 0 8px 0;
          font-size: 0.875rem;
          color: #475569;
        }

        .card-meta-row {
          display: flex;
          justify-content: space-between;
          margin-bottom: 8px;
          font-size: 0.85rem;

          .card-phone {
            color: #64748b;
          }

          .card-value {
            font-weight: 600;
            color: #15803d;
          }
        }

        .card-footer-row {
          display: flex;
          justify-content: space-between;
          border-top: 1px solid #f1f5f9;
          padding-top: 8px;
          font-size: 0.75rem;
          color: #94a3b8;

          .card-assignee {
            display: flex;
            align-items: center;
            gap: 4px;

            .tiny-icon {
              font-size: 14px;
              height: 14px;
              width: 14px;
            }
          }
        }
      }

      .desktop-only {
        display: block;
      }

      .mobile-only {
        display: none;
      }

      @media (max-width: 768px) {
        .lead-list-container {
          padding: 16px;
        }

        .desktop-only {
          display: none;
        }

        .mobile-only {
          display: flex;
        }

        .filter-row {
          flex-direction: column;
          align-items: stretch;

          .search-field,
          .filter-select {
            width: 100%;
          }
        }
      }
    `,
  ],
})
export class LeadListComponent implements OnInit {
  private readonly leadService = inject(LeadService);
  public readonly authService = inject(AuthService);
  private readonly router = inject(Router);
  private readonly dialog = inject(MatDialog);
  private readonly destroyRef = inject(DestroyRef);

  readonly displayedColumns = [
    'id',
    'customer',
    'title',
    'stage',
    'assigned_to',
    'value',
    'created_at',
    'actions',
  ];

  readonly leads = signal<Lead[]>([]);
  readonly stages = signal<Stage[]>([]);
  readonly staffUsers = signal<User[]>([]);
  readonly totalCount = signal(0);
  readonly pageSize = signal(20);
  readonly pageIndex = signal(0);
  readonly isLoading = signal(false);
  readonly errorMessage = signal<string | null>(null);

  readonly searchControl = new FormControl('');
  readonly stageFilterControl = new FormControl('');
  readonly sourceFilterControl = new FormControl('');
  readonly assigneeFilterControl = new FormControl('');
  readonly orderingControl = new FormControl('-created_at');

  ngOnInit(): void {
    this.loadStages();
    if (this.authService.isManagerOrAdmin()) {
      this.loadStaffUsers();
    }
    this.setupFilterListeners();
    this.loadLeads();
  }

  private setupFilterListeners(): void {
    this.searchControl.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef), debounceTime(300), distinctUntilChanged())
      .subscribe(() => {
        this.pageIndex.set(0);
        this.loadLeads();
      });

    this.stageFilterControl.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
      this.pageIndex.set(0);
      this.loadLeads();
    });

    this.sourceFilterControl.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => {
        this.pageIndex.set(0);
        this.loadLeads();
      });

    this.assigneeFilterControl.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => {
        this.pageIndex.set(0);
        this.loadLeads();
      });

    this.orderingControl.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
      this.pageIndex.set(0);
      this.loadLeads();
    });
  }

  private loadStages(): void {
    this.leadService.getStages().subscribe({
      next: (stages) => this.stages.set(stages),
      error: () => {},
    });
  }

  private loadStaffUsers(): void {
    this.leadService.getUsers().subscribe({
      next: (users) => this.staffUsers.set(users),
      error: () => {},
    });
  }

  loadLeads(): void {
    this.isLoading.set(true);
    this.errorMessage.set(null);

    const params: LeadFilterParams = {
      page: this.pageIndex() + 1,
      page_size: this.pageSize(),
      search: this.searchControl.value?.trim() || undefined,
      stage: this.stageFilterControl.value || undefined,
      source: this.sourceFilterControl.value || undefined,
      assigned_to: this.assigneeFilterControl.value || undefined,
      ordering: this.orderingControl.value || undefined,
    };

    this.leadService.getLeads(params).subscribe({
      next: (res: PaginatedLeadList) => {
        this.isLoading.set(false);
        this.leads.set(res.results);
        this.totalCount.set(res.count);
      },
      error: (err) => {
        this.isLoading.set(false);
        this.errorMessage.set(err.error?.detail || 'Failed to load leads from the server.');
      },
    });
  }

  onPageChange(event: PageEvent): void {
    this.pageIndex.set(event.pageIndex);
    this.pageSize.set(event.pageSize);
    this.loadLeads();
  }

  onRowClick(leadId: number): void {
    this.router.navigate(['/leads', leadId]);
  }

  openQuickAddDialog(): void {
    const dialogRef = this.dialog.open(QuickAddLeadDialogComponent, {
      width: '640px',
      maxWidth: '95vw',
      panelClass: 'quick-add-dialog-panel',
    });

    dialogRef.afterClosed().subscribe((result) => {
      if (result && result.created) {
        this.loadLeads();
      }
    });
  }
}
