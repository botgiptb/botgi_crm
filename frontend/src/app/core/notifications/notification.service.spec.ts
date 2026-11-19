import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed, fakeAsync, tick } from '@angular/core/testing';
import { signal } from '@angular/core';
import { AuthService } from '../auth/auth.service';
import { NotificationService } from './notification.service';

describe('NotificationService', () => {
  let service: NotificationService;
  let httpMock: HttpTestingController;
  let isAuthSignal: ReturnType<typeof signal<boolean>>;

  beforeEach(() => {
    isAuthSignal = signal<boolean>(false);

    const authServiceMock = {
      isAuthenticated: () => isAuthSignal(),
    };

    TestBed.configureTestingModule({
      providers: [
        NotificationService,
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: AuthService, useValue: authServiceMock },
      ],
    });

    service = TestBed.inject(NotificationService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    isAuthSignal.set(false);
    TestBed.flushEffects();
    service.ngOnDestroy();
    httpMock.verify();
  });

  it('should initialize with 0 unread count and no active polling when unauthenticated', () => {
    expect(service.unreadCount()).toBe(0);
    httpMock.expectNone('/api/notifications/unread_count/');
  });

  it('should start polling when authenticated and update unreadCount', fakeAsync(() => {
    isAuthSignal.set(true);
    TestBed.flushEffects();

    // Initial immediate fetch
    const req1 = httpMock.expectOne('/api/notifications/unread_count/');
    req1.flush({ unread_count: 5 });
    expect(service.unreadCount()).toBe(5);

    // After 30 seconds -> second poll
    tick(30000);
    const req2 = httpMock.expectOne('/api/notifications/unread_count/');
    req2.flush({ unread_count: 7 });
    expect(service.unreadCount()).toBe(7);

    // Logout stops polling and resets count
    isAuthSignal.set(false);
    TestBed.flushEffects();
    expect(service.unreadCount()).toBe(0);

    tick(30000);
    httpMock.expectNone('/api/notifications/unread_count/');
  }));

  it('should pause polling when document is hidden and resume on visible', fakeAsync(() => {
    isAuthSignal.set(true);
    TestBed.flushEffects();

    const req1 = httpMock.expectOne('/api/notifications/unread_count/');
    req1.flush({ unread_count: 3 });

    // Simulate tab becoming hidden
    spyOnProperty(document, 'visibilityState', 'get').and.returnValue('hidden');
    document.dispatchEvent(new Event('visibilitychange'));

    // Advance 60 seconds - no polls should trigger while hidden
    tick(60000);
    httpMock.expectNone('/api/notifications/unread_count/');

    // Simulate tab becoming visible again
    (
      Object.getOwnPropertyDescriptor(document, 'visibilityState')?.get as jasmine.Spy
    ).and.returnValue('visible');
    document.dispatchEvent(new Event('visibilitychange'));

    // Should immediately trigger an update fetch upon becoming visible
    const reqVisible = httpMock.expectOne('/api/notifications/unread_count/');
    reqVisible.flush({ unread_count: 4 });
    expect(service.unreadCount()).toBe(4);

    isAuthSignal.set(false);
    TestBed.flushEffects();
  }));
});
