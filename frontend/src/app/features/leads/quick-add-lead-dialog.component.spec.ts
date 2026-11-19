import { ComponentFixture, TestBed, fakeAsync, tick } from '@angular/core/testing';
import { MatDialogRef } from '@angular/material/dialog';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { Router } from '@angular/router';
import { of, throwError } from 'rxjs';
import { AuthService } from '../../core/auth/auth.service';
import { CheckPhoneResponse, Lead } from '../../core/models/lead.model';
import { LeadService } from '../../core/services/lead.service';
import { QuickAddLeadDialogComponent } from './quick-add-lead-dialog.component';

describe('QuickAddLeadDialogComponent', () => {
  let component: QuickAddLeadDialogComponent;
  let fixture: ComponentFixture<QuickAddLeadDialogComponent>;
  let leadServiceSpy: jasmine.SpyObj<LeadService>;
  let authServiceSpy: jasmine.SpyObj<AuthService>;
  let dialogRefSpy: jasmine.SpyObj<MatDialogRef<QuickAddLeadDialogComponent>>;
  let routerSpy: jasmine.SpyObj<Router>;

  beforeEach(async () => {
    leadServiceSpy = jasmine.createSpyObj('LeadService', ['checkPhone', 'createLead']);
    authServiceSpy = jasmine.createSpyObj('AuthService', ['login']);
    Object.defineProperty(authServiceSpy, 'isManagerOrAdmin', {
      value: jasmine.createSpy('isManagerOrAdmin').and.returnValue(false),
    });
    dialogRefSpy = jasmine.createSpyObj('MatDialogRef', ['close']);
    routerSpy = jasmine.createSpyObj('Router', ['navigate']);

    leadServiceSpy.checkPhone.and.returnValue(
      of({ exists: false, customer: null, open_leads: [] }),
    );

    await TestBed.configureTestingModule({
      imports: [QuickAddLeadDialogComponent, NoopAnimationsModule],
      providers: [
        { provide: LeadService, useValue: leadServiceSpy },
        { provide: AuthService, useValue: authServiceSpy },
        { provide: MatDialogRef, useValue: dialogRefSpy },
        { provide: Router, useValue: routerSpy },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(QuickAddLeadDialogComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should initialize with invalid form and disabled submit', () => {
    expect(component.leadForm.valid).toBeFalse();
    expect(component.isSubmitDisabled()).toBeTrue();
  });

  it('should debounce phone lookup by 400ms and autofill recognized customer details', fakeAsync(() => {
    const mockCheckResponse: CheckPhoneResponse = {
      exists: true,
      customer: {
        id: 42,
        name: 'Jane Doe',
        email: 'jane@example.com',
        company_name: 'Tech Corp',
        customer_type: 'business',
      },
      open_leads: [],
    };
    leadServiceSpy.checkPhone.and.returnValue(of(mockCheckResponse));

    component.leadForm.patchValue({ customer_phone: '9876543210' });
    expect(leadServiceSpy.checkPhone).not.toHaveBeenCalled();

    tick(400);

    expect(leadServiceSpy.checkPhone).toHaveBeenCalledWith('9876543210');
    expect(component.phoneCheckResult()).toEqual(mockCheckResponse);
    expect(component.leadForm.get('customer_name')?.value).toBe('Jane Doe');
    expect(component.leadForm.get('customer_email')?.value).toBe('jane@example.com');
    expect(component.leadForm.get('company_name')?.value).toBe('Tech Corp');
    expect(component.leadForm.get('customer_type')?.value).toBe('business');
  }));

  it('should handle 429 Too Many Requests gracefully without blocking form entry', fakeAsync(() => {
    leadServiceSpy.checkPhone.and.returnValue(
      throwError(() => ({ status: 429, error: { detail: 'Throttled' } })),
    );

    component.leadForm.patchValue({ customer_phone: '9876543210' });
    tick(400);

    expect(component.rateLimitWarning()).toContain('rate-limited');
    expect(component.isCheckingPhone()).toBeFalse();
  }));

  it('should display duplicate warning and disable submit until explicit choice is made when open leads exist', fakeAsync(() => {
    const mockCheckWithOpenLeads: CheckPhoneResponse = {
      exists: true,
      customer: { id: 10, name: 'Alice Smith' },
      open_leads: [
        {
          id: 101,
          stage_name: 'Quoted',
          assigned_to_name: 'bob',
          is_assigned_to_me: false,
          deal_value: '25000',
        },
      ],
    };
    leadServiceSpy.checkPhone.and.returnValue(of(mockCheckWithOpenLeads));

    component.leadForm.patchValue({
      customer_phone: '9876543210',
      customer_name: 'Alice Smith',
      source: 'walk_in',
    });
    tick(400);
    fixture.detectChanges();

    expect(component.openLeads().length).toBe(1);
    // Submit must be disabled because explicit choice has not been selected
    expect(component.isSubmitDisabled()).toBeTrue();

    // Selecting 'create_another' enables submission
    component.duplicateActionControl.setValue('create_another');
    expect(component.isSubmitDisabled()).toBeFalse();
  }));

  it('should close dialog and navigate to existing lead when openExistingLead is clicked', () => {
    component.openExistingLead(101);
    expect(dialogRefSpy.close).toHaveBeenCalled();
    expect(routerSpy.navigate).toHaveBeenCalledWith(['/leads', 101]);
  });

  it('should call createLead on submit and close dialog on success', fakeAsync(() => {
    leadServiceSpy.createLead.and.returnValue(
      of({
        lead: { id: 200, title: 'New Laptop', customer_name: 'Bob' } as unknown as Lead,
        existing_customer: false,
        open_leads_warning: [],
      }),
    );

    component.leadForm.patchValue({
      customer_phone: '9876543210',
      customer_name: 'Bob Builder',
      source: 'walk_in',
      title: 'New Laptop',
    });

    component.onSubmit();
    tick();

    expect(leadServiceSpy.createLead).toHaveBeenCalled();
    expect(dialogRefSpy.close).toHaveBeenCalledWith({
      created: true,
      lead: jasmine.objectContaining({ id: 200 }),
    });
  }));
});
