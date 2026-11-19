import { TestBed } from '@angular/core/testing';
import { ActivatedRouteSnapshot, Router, RouterStateSnapshot, UrlTree } from '@angular/router';
import { authGuard, managerGuard } from './auth.guard';
import { AuthService } from './auth.service';

describe('Auth Guards', () => {
  let router: Router;
  let authServiceSpy: jasmine.SpyObj<AuthService>;

  const mockRoute = {} as ActivatedRouteSnapshot;
  const mockState = { url: '/leads' } as RouterStateSnapshot;

  beforeEach(() => {
    authServiceSpy = jasmine.createSpyObj<AuthService>('AuthService', [
      'isAuthenticated',
      'isManagerOrAdmin',
    ]);

    TestBed.configureTestingModule({
      providers: [{ provide: AuthService, useValue: authServiceSpy }],
    });

    router = TestBed.inject(Router);
  });

  describe('authGuard', () => {
    it('should allow access when authenticated', () => {
      authServiceSpy.isAuthenticated.and.returnValue(true);

      const result = TestBed.runInInjectionContext(() => authGuard(mockRoute, mockState));
      expect(result).toBeTrue();
    });

    it('should redirect to /login with returnUrl when not authenticated', () => {
      authServiceSpy.isAuthenticated.and.returnValue(false);

      const result = TestBed.runInInjectionContext(() => authGuard(mockRoute, mockState));
      expect(result instanceof UrlTree).toBeTrue();
      const urlTree = result as UrlTree;
      expect(router.serializeUrl(urlTree)).toBe('/login?returnUrl=%2Fleads');
    });
  });

  describe('managerGuard', () => {
    it('should allow access when user is manager or admin', () => {
      authServiceSpy.isAuthenticated.and.returnValue(true);
      authServiceSpy.isManagerOrAdmin.and.returnValue(true);

      const result = TestBed.runInInjectionContext(() => managerGuard(mockRoute, mockState));
      expect(result).toBeTrue();
    });

    it('should redirect staff to home /', () => {
      authServiceSpy.isAuthenticated.and.returnValue(true);
      authServiceSpy.isManagerOrAdmin.and.returnValue(false);

      const result = TestBed.runInInjectionContext(() => managerGuard(mockRoute, mockState));
      expect(result instanceof UrlTree).toBeTrue();
      const urlTree = result as UrlTree;
      expect(router.serializeUrl(urlTree)).toBe('/');
    });
  });
});
