import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from './auth.service';

export const authGuard: CanActivateFn = (route, state) => {
  const authService = inject(AuthService);
  const router = inject(Router);

  if (authService.isAuthenticated()) {
    return true;
  }

  // Redirect unauthenticated user to /login with returnUrl parameter
  return router.createUrlTree(['/login'], {
    queryParams: { returnUrl: state.url },
  });
};

export const managerGuard: CanActivateFn = (_route, _state) => {
  const authService = inject(AuthService);
  const router = inject(Router);

  if (authService.isAuthenticated() && authService.isManagerOrAdmin()) {
    return true;
  }

  return router.createUrlTree(['/']);
};
