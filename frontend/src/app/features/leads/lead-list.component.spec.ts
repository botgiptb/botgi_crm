import { ComponentFixture, TestBed, fakeAsync, tick } from '@angular/core/testing';
import { MatDialog, MatDialogRef } from '@angular/material/dialog';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { Router } from '@angular/router';
import { of, throwError } from 'rxjs';
import { AuthService } from '../../core/auth/auth.service';
import { Lead, PaginatedLeadList, Stage } from '../../core/models/lead.model';
import { User } from '../../core/models/user.model';
import { LeadService } from '../../core/services/lead.service';
import { LeadListComponent } from './lead-list.component';
import { QuickAddLeadDialogComponent } from './quick-add-lead-dialog.component';

describe('LeadListComponent', () => {
  let component: LeadListComponent;
  let fixture: ComponentFixture<LeadListComponent>;
  let leadServiceSpy: jasmine.SpyObj<LeadService>;
  let authServiceSpy: jasmine.SpyObj<AuthService>;
  let routerSpy: jasmine.SpyObj<Router>;
  let dialogSpy: jasmine.SpyObj<MatDialog>;

  const mockStages: Stage[] = [
    { id: 1, name: 'New Lead', slug: 'new', order: 1 } as unknown as Stage,
    { id: 2, name: 'Contacted', slug: 'contacted', order: 2 } as unknown as Stage,
  ];

  const mockUsers: User[] = [
    {
      id: 10,
      username: 'sales_rep_1',
      email: 'rep1@example.com',
      role: 'staff',
    } as unknown as User,
    {
      id: 20,
      username: 'sales_rep_2',
      email: 'rep2@example.com',
      role: 'staff',
    } as unknown as User,
  ];

  const mockLeadsResponse: PaginatedLeadList = {
    count: 2,
    results: [
      {
        id: 1,
        title: 'Gaming PC Build',
        customer_name: 'John Doe',
        customer_phone: '9876543210',
        stage_name: 'New Lead',
        stage_slug: 'new',
        assigned_to_name: 'sales_rep_1',
        deal_value: '85000',
        created_at: '2026-11-18T10:00:00Z',
      } as unknown as Lead,
      {
        id: 2,
        title: 'Office Laptop',
        customer_name: 'Mary Jane',
        customer_phone: '9876543211',
        stage_name: 'Contacted',
        stage_slug: 'contacted',
        assigned_to_name: 'sales_rep_2',
        deal_value: '45000',
        created_at: '2026-11-18T11:00:00Z',
      } as unknown as Lead,
    ],
  };

  beforeEach(async () => {
    leadServiceSpy = jasmine.createSpyObj('LeadService', ['getLeads', 'getStages', 'getUsers']);
    authServiceSpy = jasmine.createSpyObj('AuthService', ['login']);
    Object.defineProperty(authServiceSpy, 'isManagerOrAdmin', {
      value: jasmine.createSpy('isManagerOrAdmin').and.returnValue(true),
    });
    routerSpy = jasmine.createSpyObj('Router', ['navigate']);
    dialogSpy = jasmine.createSpyObj('MatDialog', ['open']);
    leadServiceSpy.getStages.and.returnValue(of(mockStages));
    leadServiceSpy.getUsers.and.returnValue(of(mockUsers));
    leadServiceSpy.getLeads.and.returnValue(of(mockLeadsResponse));

    await TestBed.configureTestingModule({
      imports: [LeadListComponent, NoopAnimationsModule],
      providers: [
        { provide: LeadService, useValue: leadServiceSpy },
        { provide: AuthService, useValue: authServiceSpy },
        { provide: Router, useValue: routerSpy },
        { provide: MatDialog, useValue: dialogSpy },
      ],
    })
      .overrideProvider(MatDialog, { useValue: dialogSpy })
      .compileComponents();

    fixture = TestBed.createComponent(LeadListComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should load stages, staff users and leads on init', () => {
    expect(leadServiceSpy.getStages).toHaveBeenCalled();
    expect(leadServiceSpy.getUsers).toHaveBeenCalled();
    expect(leadServiceSpy.getLeads).toHaveBeenCalledWith(
      jasmine.objectContaining({
        page: 1,
        page_size: 20,
        ordering: '-created_at',
      }),
    );
    expect(component.leads().length).toBe(2);
    expect(component.totalCount()).toBe(2);
  });

  it('should debounce search input by 300ms before triggering lead reload', fakeAsync(() => {
    leadServiceSpy.getLeads.calls.reset();

    component.searchControl.setValue('John');
    expect(leadServiceSpy.getLeads).not.toHaveBeenCalled();

    tick(300);

    expect(leadServiceSpy.getLeads).toHaveBeenCalledWith(
      jasmine.objectContaining({
        search: 'John',
        page: 1,
      }),
    );
  }));

  it('should reset page index to 0 and reload leads when stage or source filter changes', () => {
    leadServiceSpy.getLeads.calls.reset();
    component.pageIndex.set(2);

    component.stageFilterControl.setValue('1');

    expect(component.pageIndex()).toBe(0);
    expect(leadServiceSpy.getLeads).toHaveBeenCalledWith(
      jasmine.objectContaining({
        stage: '1',
        page: 1,
      }),
    );
  });

  it('should reload leads with updated page and page_size on pagination change', () => {
    leadServiceSpy.getLeads.calls.reset();

    component.onPageChange({ pageIndex: 1, pageSize: 50, length: 100 });

    expect(component.pageIndex()).toBe(1);
    expect(component.pageSize()).toBe(50);
    expect(leadServiceSpy.getLeads).toHaveBeenCalledWith(
      jasmine.objectContaining({
        page: 2,
        page_size: 50,
      }),
    );
  });

  it('should navigate to /leads/:id when a lead row is clicked', () => {
    component.onRowClick(42);
    expect(routerSpy.navigate).toHaveBeenCalledWith(['/leads', 42]);
  });

  it('should open QuickAddLeadDialog and refresh leads on successful creation', () => {
    const dialogRefMock = {
      afterClosed: () => of({ created: true }),
    };
    dialogSpy.open.and.returnValue(
      dialogRefMock as unknown as MatDialogRef<QuickAddLeadDialogComponent>,
    );
    leadServiceSpy.getLeads.calls.reset();

    component.openQuickAddDialog();

    expect(dialogSpy.open).toHaveBeenCalled();
    expect(leadServiceSpy.getLeads).toHaveBeenCalled();
  });

  it('should display error message on backend failure', () => {
    leadServiceSpy.getLeads.and.returnValue(
      throwError(() => ({ error: { detail: 'Network connectivity lost' } })),
    );

    component.loadLeads();

    expect(component.errorMessage()).toBe('Network connectivity lost');
    expect(component.isLoading()).toBeFalse();
  });
});
