import {
  HttpErrorResponse,
  HttpEvent,
  HttpHandlerFn,
  HttpInterceptorFn,
  HttpRequest,
} from '@angular/common/http';
import { inject } from '@angular/core';
import {
  Observable,
  catchError,
  finalize,
  firstValueFrom,
  from,
  shareReplay,
  switchMap,
  throwError,
} from 'rxjs';
import { AuthService } from './auth.service';

let refreshInProgress$: Observable<string> | null = null;

export function resetAuthInterceptorState(): void {
  refreshInProgress$ = null;
}

function performRefresh(authService: AuthService): Observable<string> {
  if (
    typeof navigator !== 'undefined' &&
    'locks' in navigator &&
    navigator.locks &&
    typeof navigator.locks.request === 'function'
  ) {
    return from(
      navigator.locks.request('auth-refresh-lock', async () => {
        // Check if another tab refreshed the token while waiting for lock
        const existingToken = authService.getAccessToken();
        if (existingToken) {
          return existingToken;
        }
        return await firstValueFrom(authService.refresh());
      }),
    );
  }
  return authService.refresh();
}

export const authInterceptor: HttpInterceptorFn = (
  req: HttpRequest<unknown>,
  next: HttpHandlerFn,
): Observable<HttpEvent<unknown>> => {
  const authService = inject(AuthService);

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

      // Handle backend network errors (status 0)
      if (error.status === 0) {
        authService.isOffline.set(true);
        return throwError(() => error);
      }

      // If not 401, or auth endpoint, or already retried once -> do not retry
      if (error.status !== 401 || isAuthEndpoint || alreadyRetried) {
        return throwError(() => error);
      }

      // Coalesce parallel 401s onto a single shared refresh Observable
      if (!refreshInProgress$) {
        refreshInProgress$ = performRefresh(authService).pipe(
          shareReplay({ bufferSize: 1, refCount: true }),
          finalize(() => {
            refreshInProgress$ = null;
          }),
        );
      }

      return refreshInProgress$.pipe(
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
        catchError((refreshErr: unknown) => {
          if (refreshErr instanceof HttpErrorResponse) {
            if (refreshErr.status === 0) {
              authService.isOffline.set(true);
            } else if (refreshErr.status === 401 || refreshErr.status === 403) {
              authService.logout(true);
            }
          }
          return throwError(() => refreshErr);
        }),
      );
    }),
  );
};
