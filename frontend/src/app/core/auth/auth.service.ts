import { Injectable, computed, inject, signal } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Router } from '@angular/router';
import { Observable, catchError, firstValueFrom, map, of, tap, throwError } from 'rxjs';
import { AuthResponse, LoginRequest, User } from '../models/user.model';

export const AUTH_CHANNEL_NAME = 'shopcrm_auth_channel';

export interface AuthBroadcastMessage {
  type: 'LOGOUT' | 'LOGIN';
}

@Injectable({
  providedIn: 'root',
})
export class AuthService {
  private http = inject(HttpClient);
  private router = inject(Router);

  // Auth State Signals
  readonly currentUser = signal<User | null>(null);
  readonly isInitializing = signal<boolean>(true);
  readonly isOffline = signal<boolean>(false);

  // Computed State
  readonly isAuthenticated = computed(() => !!this.currentUser());
  readonly userRole = computed(() => this.currentUser()?.role ?? null);
  readonly isManagerOrAdmin = computed(() => {
    const role = this.userRole();
    return role === 'admin' || role === 'manager';
  });

  // Short-lived JWT access token kept strictly in memory
  private accessToken: string | null = null;
  private broadcastChannel: BroadcastChannel | null = null;

  constructor() {
    if (typeof window !== 'undefined' && 'BroadcastChannel' in window) {
      this.broadcastChannel = new BroadcastChannel(AUTH_CHANNEL_NAME);
      this.broadcastChannel.onmessage = (event: MessageEvent<AuthBroadcastMessage>) => {
        if (event.data?.type === 'LOGOUT') {
          this.handleCrossTabLogout();
        }
      };
    }
  }

  getAccessToken(): string | null {
    return this.accessToken;
  }

  setAccessToken(token: string | null): void {
    this.accessToken = token;
  }

  /**
   * Log in user, store access token in memory, and set current user.
   */
  login(credentials: LoginRequest): Observable<AuthResponse> {
    return this.http
      .post<AuthResponse>('/api/auth/login/', credentials, { withCredentials: true })
      .pipe(
        tap((res) => {
          this.accessToken = res.access;
          this.currentUser.set(res.user);
          this.isOffline.set(false);
          this.broadcastChannel?.postMessage({ type: 'LOGIN' });
        }),
      );
  }

  /**
   * Silent refresh of the access token using httpOnly cookie.
   */
  refresh(): Observable<string> {
    return this.http
      .post<AuthResponse>('/api/auth/refresh/', {}, { withCredentials: true })
      .pipe(
        tap((res) => {
          this.accessToken = res.access;
          this.currentUser.set(res.user);
          this.isOffline.set(false);
        }),
        map((res) => res.access),
      );
  }

  /**
   * Log out current user, invalidate cookie/blacklist token, and redirect to /login.
   */
  logout(broadcast: boolean = true): Observable<void> {
    return this.http
      .post<{ message: string }>('/api/auth/logout/', {}, { withCredentials: true })
      .pipe(
        catchError(() => of({ message: 'Logged out' })),
        map(() => void 0),
        tap(() => {
          this.clearLocalSession();
          if (broadcast) {
            this.broadcastChannel?.postMessage({ type: 'LOGOUT' });
          }
          this.router.navigate(['/login']);
        }),
      );
  }

  /**
   * Called when another tab emits a LOGOUT event.
   */
  handleCrossTabLogout(): void {
    this.clearLocalSession();
    this.router.navigate(['/login']);
  }

  private clearLocalSession(): void {
    this.accessToken = null;
    this.currentUser.set(null);
  }

  /**
   * Initial app startup verification. Runs inside APP_INITIALIZER.
   */
  async initAuth(): Promise<void> {
    try {
      await firstValueFrom(this.refresh());
      this.isOffline.set(false);
    } catch (err: unknown) {
      if (err instanceof HttpErrorResponse) {
        if (err.status === 0) {
          // Network error or backend unreachable -> mark offline state
          this.isOffline.set(true);
        } else if (err.status === 401 || err.status === 403) {
          // Not logged in or expired session -> clear state without throwing
          this.clearLocalSession();
        }
      }
    } finally {
      this.isInitializing.set(false);
    }
  }
}
