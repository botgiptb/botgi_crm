import { HttpClient } from '@angular/common/http';
import { Injectable, OnDestroy, effect, inject, signal } from '@angular/core';
import { Subscription, interval } from 'rxjs';
import { AuthService } from '../auth/auth.service';

interface UnreadCountResponse {
  unread_count: number;
}

@Injectable({
  providedIn: 'root',
})
export class NotificationService implements OnDestroy {
  private http = inject(HttpClient);
  private authService = inject(AuthService);

  readonly unreadCount = signal<number>(0);
  private pollSub: Subscription | null = null;
  private visibilityListener: (() => void) | null = null;

  constructor() {
    // Reactively start or stop polling based on authentication state
    effect(() => {
      const isAuth = this.authService.isAuthenticated();
      if (isAuth) {
        this.startPolling();
      } else {
        this.stopPolling();
        this.unreadCount.set(0);
      }
    });

    // Handle visibility changes: pause when tab hidden, fetch immediately on visible
    if (typeof document !== 'undefined') {
      this.visibilityListener = () => {
        if (document.visibilityState === 'visible') {
          if (this.authService.isAuthenticated()) {
            this.startPolling();
          }
        } else {
          this.stopPolling();
        }
      };
      document.addEventListener('visibilitychange', this.visibilityListener);
    }
  }

  fetchUnreadCount(): void {
    if (!this.authService.isAuthenticated()) {
      return;
    }

    this.http
      .get<UnreadCountResponse>('/api/notifications/unread_count/', { withCredentials: true })
      .subscribe({
        next: (data) => {
          this.unreadCount.set(data.unread_count ?? 0);
        },
        error: () => {
          // Silent failure on polling error
        },
      });
  }

  private startPolling(): void {
    this.stopPolling();
    this.fetchUnreadCount();

    // Poll every 30 seconds
    this.pollSub = interval(30000).subscribe(() => {
      if (typeof document === 'undefined' || document.visibilityState === 'visible') {
        this.fetchUnreadCount();
      }
    });
  }

  private stopPolling(): void {
    if (this.pollSub) {
      this.pollSub.unsubscribe();
      this.pollSub = null;
    }
  }

  ngOnDestroy(): void {
    this.stopPolling();
    if (typeof document !== 'undefined' && this.visibilityListener) {
      document.removeEventListener('visibilitychange', this.visibilityListener);
    }
  }
}
