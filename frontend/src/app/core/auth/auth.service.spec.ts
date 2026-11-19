import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { AuthResponse, User } from '../models/user.model';
import { AuthService } from './auth.service';

describe('AuthService', () => {
  let service: AuthService;
  let httpMock: HttpTestingController;
  let routerSpy: jasmine.SpyObj<Router>;

  const mockUser: User = {
    id: 1,
    username: 'teststaff',
    email: 'test@shopcrm.local',
    role: 'staff',
    first_name: 'Test',
    last_name: 'Staff',
    receives_meta_leads: true,
    last_meta_lead_assigned_at: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  };

  const mockAuthResponse: AuthResponse = {
    access: 'mock-access-token-jwt',
    user: mockUser,
  };

  beforeEach(() => {
    routerSpy = jasmine.createSpyObj('Router', ['navigate']);

    TestBed.configureTestingModule({
      providers: [
        AuthService,
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: Router, useValue: routerSpy },
      ],
    });

    service = TestBed.inject(AuthService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should be created with initial unauthenticated state', () => {
    expect(service).toBeTruthy();
    expect(service.isAuthenticated()).toBeFalse();
    expect(service.currentUser()).toBeNull();
    expect(service.getAccessToken()).toBeNull();
  });

  it('login should store access token in memory and set currentUser', () => {
    service.login({ username: 'teststaff', password: 'password123' }).subscribe((res) => {
      expect(res).toEqual(mockAuthResponse);
    });

    const req = httpMock.expectOne('/api/auth/login/');
    expect(req.request.method).toBe('POST');
    expect(req.request.withCredentials).toBeTrue();
    req.flush(mockAuthResponse);

    expect(service.getAccessToken()).toBe('mock-access-token-jwt');
    expect(service.currentUser()).toEqual(mockUser);
    expect(service.isAuthenticated()).toBeTrue();
    expect(service.userRole()).toBe('staff');
    expect(service.isManagerOrAdmin()).toBeFalse();
  });

  it('refresh should update access token and currentUser', () => {
    service.refresh().subscribe((token) => {
      expect(token).toBe('mock-access-token-jwt');
    });

    const req = httpMock.expectOne('/api/auth/refresh/');
    expect(req.request.method).toBe('POST');
    expect(req.request.withCredentials).toBeTrue();
    req.flush(mockAuthResponse);

    expect(service.getAccessToken()).toBe('mock-access-token-jwt');
    expect(service.isAuthenticated()).toBeTrue();
  });

  it('logout should clear access token and currentUser, and navigate to /login', () => {
    service.setAccessToken('some-token');
    service.currentUser.set(mockUser);

    service.logout(false).subscribe();

    const req = httpMock.expectOne('/api/auth/logout/');
    expect(req.request.method).toBe('POST');
    expect(req.request.withCredentials).toBeTrue();
    req.flush({ message: 'Logged out successfully.' });

    expect(service.getAccessToken()).toBeNull();
    expect(service.currentUser()).toBeNull();
    expect(service.isAuthenticated()).toBeFalse();
    expect(routerSpy.navigate).toHaveBeenCalledWith(['/login']);
  });

  it('initAuth should set isOffline on status 0 network error without clearing state', async () => {
    const initPromise = service.initAuth();

    const req = httpMock.expectOne('/api/auth/refresh/');
    req.error(new ProgressEvent('error'), { status: 0, statusText: 'Unknown Error' });

    await initPromise;
    expect(service.isOffline()).toBeTrue();
    expect(service.isInitializing()).toBeFalse();
  });

  it('initAuth should cleanly clear state on 401 without setting offline', async () => {
    const initPromise = service.initAuth();

    const req = httpMock.expectOne('/api/auth/refresh/');
    req.flush(
      { detail: 'Refresh token cookie missing.' },
      { status: 401, statusText: 'Unauthorized' },
    );

    await initPromise;
    expect(service.isOffline()).toBeFalse();
    expect(service.isAuthenticated()).toBeFalse();
    expect(service.isInitializing()).toBeFalse();
  });
});
