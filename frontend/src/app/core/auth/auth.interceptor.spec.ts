import { HttpClient, HttpErrorResponse, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { authInterceptor, resetAuthInterceptorState } from './auth.interceptor';
import { AuthService } from './auth.service';

describe('authInterceptor', () => {
  let http: HttpClient;
  let httpMock: HttpTestingController;
  let authServiceSpy: jasmine.SpyObj<AuthService>;

  beforeEach(() => {
    resetAuthInterceptorState();

    authServiceSpy = jasmine.createSpyObj<AuthService>('AuthService', [
      'getAccessToken',
      'refresh',
      'logout',
    ]);
    const isOfflineMock = jasmine.createSpy('set');
    Object.defineProperty(authServiceSpy, 'isOffline', {
      value: { set: isOfflineMock },
    });

    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([authInterceptor])),
        provideHttpClientTesting(),
        { provide: AuthService, useValue: authServiceSpy },
      ],
    });

    http = TestBed.inject(HttpClient);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
    resetAuthInterceptorState();
  });

  it('should attach Bearer token to requests when available', () => {
    authServiceSpy.getAccessToken.and.returnValue('valid-token-123');

    http.get('/api/leads/').subscribe();

    const req = httpMock.expectOne('/api/leads/');
    expect(req.request.headers.get('Authorization')).toBe('Bearer valid-token-123');
    expect(req.request.withCredentials).toBeTrue();
    req.flush([]);
  });

  it('should not attach token or trigger refresh on auth calls', () => {
    authServiceSpy.getAccessToken.and.returnValue('some-token');

    http.post('/api/auth/login/', { username: 'u', password: 'p' }).subscribe({
      error: (err) => expect(err.status).toBe(401),
    });

    const req = httpMock.expectOne('/api/auth/login/');
    expect(req.request.headers.has('Authorization')).toBeFalse();
    req.flush({ detail: 'Invalid credentials' }, { status: 401, statusText: 'Unauthorized' });

    expect(authServiceSpy.refresh).not.toHaveBeenCalled();
  });

  it('parallel 401s should trigger exactly one refresh call and replay all requests once', (done) => {
    let currentToken: string | null = null;
    authServiceSpy.getAccessToken.and.callFake(() => currentToken);
    authServiceSpy.refresh.and.callFake(() => {
      currentToken = 'new-refreshed-token';
      return of('new-refreshed-token');
    });

    let completed = 0;
    const checkDone = () => {
      completed++;
      if (completed === 2) {
        expect(authServiceSpy.refresh).toHaveBeenCalledTimes(1);
        done();
      }
    };

    // Fire two requests in parallel
    http.get('/api/leads/1/').subscribe((res) => {
      expect(res).toEqual({ id: 1 });
      checkDone();
    });

    http.get('/api/leads/2/').subscribe((res) => {
      expect(res).toEqual({ id: 2 });
      checkDone();
    });

    // Both fail with 401 initially
    const req1 = httpMock.expectOne('/api/leads/1/');
    const req2 = httpMock.expectOne('/api/leads/2/');

    req1.flush({ detail: 'Token expired' }, { status: 401, statusText: 'Unauthorized' });
    req2.flush({ detail: 'Token expired' }, { status: 401, statusText: 'Unauthorized' });

    // Allow async locks to process and expect replayed requests
    setTimeout(() => {
      const retry1 = httpMock.expectOne('/api/leads/1/');
      const retry2 = httpMock.expectOne('/api/leads/2/');

      expect(retry1.request.headers.get('Authorization')).toBe('Bearer new-refreshed-token');
      expect(retry1.request.headers.get('X-Auth-Retried')).toBe('true');
      expect(retry2.request.headers.get('Authorization')).toBe('Bearer new-refreshed-token');
      expect(retry2.request.headers.get('X-Auth-Retried')).toBe('true');

      retry1.flush({ id: 1 });
      retry2.flush({ id: 2 });
    }, 50);
  });

  it('should replay only once and propagate error if replayed request still returns 401', (done) => {
    let currentToken: string | null = null;
    authServiceSpy.getAccessToken.and.callFake(() => currentToken);
    authServiceSpy.refresh.and.callFake(() => {
      currentToken = 'new-token';
      return of('new-token');
    });

    http.get('/api/leads/').subscribe({
      error: (err) => {
        expect(err.status).toBe(401);
        expect(authServiceSpy.refresh).toHaveBeenCalledTimes(1);
        done();
      },
    });

    // Initial 401
    const req = httpMock.expectOne('/api/leads/');
    req.flush({ detail: 'Expired' }, { status: 401, statusText: 'Unauthorized' });

    setTimeout(() => {
      // Replayed request also fails with 401
      const retry = httpMock.expectOne('/api/leads/');
      expect(retry.request.headers.get('X-Auth-Retried')).toBe('true');
      retry.flush({ detail: 'Still unauthorized' }, { status: 401, statusText: 'Unauthorized' });

      // No second retry should be issued
      httpMock.expectNone('/api/leads/');
    }, 50);
  });

  it('network error on refresh keeps the session and sets isOffline', (done) => {
    authServiceSpy.getAccessToken.and.returnValue(null);
    const networkError = new HttpErrorResponse({ status: 0, statusText: 'Unknown Error' });
    authServiceSpy.refresh.and.returnValue(throwError(() => networkError));

    http.get('/api/leads/').subscribe({
      error: () => {
        expect(authServiceSpy.isOffline.set).toHaveBeenCalledWith(true);
        expect(authServiceSpy.logout).not.toHaveBeenCalled();
        done();
      },
    });

    const req = httpMock.expectOne('/api/leads/');
    req.flush({ detail: 'Unauthorized' }, { status: 401, statusText: 'Unauthorized' });
  });

  it('401 or 403 error on refresh logs user out', (done) => {
    authServiceSpy.getAccessToken.and.returnValue(null);
    const refresh401 = new HttpErrorResponse({
      status: 401,
      statusText: 'Unauthorized',
      error: { detail: 'Refresh token blacklisted' },
    });
    authServiceSpy.refresh.and.returnValue(throwError(() => refresh401));

    http.get('/api/leads/').subscribe({
      error: () => {
        expect(authServiceSpy.logout).toHaveBeenCalledWith(true);
        done();
      },
    });

    const req = httpMock.expectOne('/api/leads/');
    req.flush({ detail: 'Token expired' }, { status: 401, statusText: 'Unauthorized' });
  });
});
