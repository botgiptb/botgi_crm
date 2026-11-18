import { HttpErrorResponse, HttpHandlerFn, HttpInterceptorFn, HttpRequest } from '@angular/common/http';
import { inject } from '@angular/core';
import { BehaviorSubject, Observable, catchError, filter, from, switchMap, take, throwError } from 'rxjs';
import { AuthService } from './auth.service';

let isRefreshing = false;
const refreshTokenSubject = new BehaviorSubject<string | null>(null);

/**
 * Execute token refresh with single-flight coalescing and cross-tab lock protection.
 */
async function performLockedRefresh(authService: AuthService): Promise<string> {
  if (typeof navigator !== 'undefined' && 'locks' in navigator) {
    return await navigator.locks.request('auth-refresh-lock', async () => {
      // Re-check if access token was already refreshed by another tab
      const currentToken = authService.getAccessToken();
      const res = await new Promise<string>((resolve, reject) => {
        authService.refresh().subscribe({
          next: (token) => resolve(token),
          error: (err) => reject(err),
        });
      });
      return res;
    });
  }

  // Fallback if Web Locks API is not available
  return await new Promise<string>((resolve, reject) => {
    authService.refresh().subscribe({
      next: (token) => resolve(token),
      error: (err) => reject(err),
    });
  });
}

export const authInterceptor: HttpInterceptorFn = (req: HttpRequest<unknown>, next: HttpHandlerFn): Observable<any> => {
  const authService = inject(AuthService);

  // 1. Skip token attachment and 401 refresh handling for auth endpoints
  const isAuthEndpoint = req.url.includes('/api/auth/');
  const alreadyRetried = req.headers.has('X-Auth-Retried');

  let authReq = req;
  const token = authService.getAccessToken();

  if (token && !isAuthEndpoint) {
    authReq = req.clone({
      setHeaders: {
        Authorization: `Bearer ${token}`,
      },
      withCredentials: true,
    });
  } else if (req.url.startsWith('/api/')) {
    authReq = req.clone({
      withCredentials: true,
    });
  }

  return next(authReq).pipe(
    catchError((error: unknown) => {
      if (!(error instanceof HttpErrorResponse)) {
        return throwError(() => error);
      }

      // Handle network errors (backend offline)
      if (error.status === 0) {
        authService.isOffline.set(true);
        return throwError(() => error);
      }

      // If it's not a 401, or is an auth endpoint, or has already been retried once -> propagate error
      if (error.status !== 401 || isAuthEndpoint || alreadyRetried) {
        return throwError(() => error);
      }

      // Handle 401: single-flight refresh coalescing
      if (!isRefreshing) {
        isRefreshing = true;
        refreshTokenSubject.next(null);

        return from(performLockedRefresh(authService)).pipe(
          switchMap((newToken: string) => {
            isRefreshing = false;
            refreshTokenSubject.next(newToken);

            // Replay original request ONCE with new access token
            const retryReq = req.clone({
              setHeaders: {
                Authorization: `Bearer ${newToken}`,
                'X-Auth-Retried': 'true',
              },
              withCredentials: true,
            });
            return next(retryReq);
          }),
          catchError((refreshErr: unknown) => {
            isRefreshing = false;
            refreshTokenSubject.next(null);

            if (refreshErr instanceof HttpErrorResponse) {
              if (refreshErr.status === 0) {
                authService.isOffline.set(true);
              } else if (refreshErr.status === 401 || refreshErr.status === 403) {
                // Refresh cookie expired or revoked -> log out
                authService.logout(true);
              }
            }
            return throwError(() => refreshErr);
          }),
        );
      } else {
        // Another refresh is in flight; wait for it to emit the new token
        return refreshTokenSubject.pipe(
          filter((token) => token !== null),
          take(1),
          switchMap((newToken: string) => {
            const retryReq = req.clone({
              setHeaders: {
                Authorization: `Bearer ${newToken}`,
                'X-Auth-Retried': 'true',
              },
              withCredentials: true,
            });
            return next(retryReq);
          }),
        );
      }
    }),
  );
};
