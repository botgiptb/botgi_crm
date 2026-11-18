import { CommonModule } from '@angular/common';
import { Component, inject } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { MatBadgeModule } from '@angular/material/badge';
import { MatButtonModule } from '@angular/material/button';
import { MatChipsModule } from '@angular/material/chips';
import { MatDividerModule } from '@angular/material/divider';
import { MatIconModule } from '@angular/material/icon';
import { MatListModule } from '@angular/material/list';
import { MatSidenavModule } from '@angular/material/sidenav';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AuthService } from '../core/auth/auth.service';
import { NotificationService } from '../core/notifications/notification.service';

@Component({
  selector: 'app-shell',
  standalone: true,
  imports: [
    CommonModule,
    RouterOutlet,
    RouterLink,
    RouterLinkActive,
    MatToolbarModule,
    MatSidenavModule,
    MatListModule,
    MatIconModule,
    MatButtonModule,
    MatBadgeModule,
    MatChipsModule,
    MatDividerModule,
    MatTooltipModule,
  ],
  template: `
    <div class="shell-container">
      <!-- Top Header Toolbar -->
      <mat-toolbar color="primary" class="main-toolbar">
        <button
          mat-icon-button
          (click)="sidenav.toggle()"
          class="menu-toggle-btn"
          aria-label="Toggle navigation menu"
        >
          <mat-icon>menu</mat-icon>
        </button>

        <div class="brand">
          <mat-icon class="brand-icon">computer</mat-icon>
          <span class="brand-title">Shop CRM</span>
        </div>

        <span class="spacer"></span>

        <!-- Offline Indicator Banner -->
        @if (authService.isOffline()) {
          <div class="offline-pill" matTooltip="CRM backend is unreachable">
            <mat-icon>cloud_off</mat-icon>
            <span class="offline-text">Offline</span>
          </div>
        }

        <!-- User Role Badge -->
        @if (currentUser(); as user) {
          <div class="user-info">
            <span class="user-name">{{ user.first_name || user.username }}</span>
            <span class="role-chip" [ngClass]="'role-' + user.role">
              {{ user.role | uppercase }}
            </span>
          </div>
        }

        <!-- Notification Bell -->
        <button
          mat-icon-button
          routerLink="/notifications"
          aria-label="Notifications"
          [matBadge]="unreadCount()"
          [matBadgeHidden]="unreadCount() === 0"
          matBadgeColor="warn"
          matTooltip="Notifications"
        >
          <mat-icon>notifications</mat-icon>
        </button>

        <!-- Logout Button -->
        <button
          mat-icon-button
          (click)="logout()"
          aria-label="Sign out"
          matTooltip="Sign Out"
        >
          <mat-icon>logout</mat-icon>
        </button>
      </mat-toolbar>

      <!-- Sidenav Container -->
      <mat-sidenav-container class="sidenav-container">
        <!-- Desktop / Tablet Sidenav Drawer -->
        <mat-sidenav #sidenav mode="side" opened class="app-sidenav">
          <mat-nav-list>
            <a mat-list-item routerLink="/leads" routerLinkActive="active-link">
              <mat-icon matListItemIcon>leaderboard</mat-icon>
              <div matListItemTitle>Leads</div>
            </a>

            <a mat-list-item routerLink="/notifications" routerLinkActive="active-link">
              <mat-icon
                matListItemIcon
                [matBadge]="unreadCount()"
                [matBadgeHidden]="unreadCount() === 0"
                matBadgeColor="warn"
                matBadgeSize="small"
              >
                notifications
              </mat-icon>
              <div matListItemTitle>Notifications</div>
            </a>

            @if (authService.isManagerOrAdmin()) {
              <mat-divider></mat-divider>
              <div class="nav-section-header">Manager Actions</div>

              <a mat-list-item routerLink="/unprocessed-meta-leads" routerLinkActive="active-link">
                <mat-icon matListItemIcon>contact_support</mat-icon>
                <div matListItemTitle>Unprocessed Meta Leads</div>
              </a>
            }
          </mat-nav-list>
        </mat-sidenav>

        <!-- Main Content View Area -->
        <mat-sidenav-content class="main-content">
          <div class="content-wrapper">
            <router-outlet></router-outlet>
          </div>

          <!-- Mobile Bottom Navigation Bar -->
          <nav class="mobile-bottom-nav">
            <a routerLink="/leads" routerLinkActive="mobile-active" class="bottom-nav-item">
              <mat-icon>leaderboard</mat-icon>
              <span>Leads</span>
            </a>

            <a routerLink="/notifications" routerLinkActive="mobile-active" class="bottom-nav-item">
              <mat-icon
                [matBadge]="unreadCount()"
                [matBadgeHidden]="unreadCount() === 0"
                matBadgeColor="warn"
                matBadgeSize="small"
              >
                notifications
              </mat-icon>
              <span>Alerts</span>
            </a>

            @if (authService.isManagerOrAdmin()) {
              <a routerLink="/unprocessed-meta-leads" routerLinkActive="mobile-active" class="bottom-nav-item">
                <mat-icon>contact_support</mat-icon>
                <span>Review</span>
              </a>
            }
          </nav>
        </mat-sidenav-content>
      </mat-sidenav-container>
    </div>
  `,
  styles: [
    `
      .shell-container {
        display: flex;
        flex-direction: column;
        height: 100vh;
        overflow: hidden;
      }

      .main-toolbar {
        z-index: 100;
        background-color: #0f172a;
        color: #f8fafc;
        display: flex;
        align-items: center;
        padding: 0 1rem;
        box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.1);
      }

      .brand {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        font-weight: 700;
        letter-spacing: -0.025em;
        margin-left: 0.25rem;
      }

      .brand-icon {
        color: #3b82f6;
      }

      .brand-title {
        font-size: 1.15rem;
      }

      .spacer {
        flex: 1 1 auto;
      }

      .offline-pill {
        display: flex;
        align-items: center;
        gap: 0.25rem;
        background-color: #dc2626;
        color: white;
        padding: 0.2rem 0.6rem;
        border-radius: 9999px;
        font-size: 0.75rem;
        font-weight: 600;
        margin-right: 0.75rem;
      }

      .offline-pill mat-icon {
        font-size: 14px;
        width: 14px;
        height: 14px;
      }

      .user-info {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        margin-right: 0.75rem;
      }

      .user-name {
        font-size: 0.875rem;
        font-weight: 500;
      }

      .role-chip {
        font-size: 0.65rem;
        font-weight: 700;
        padding: 0.15rem 0.45rem;
        border-radius: 4px;
        letter-spacing: 0.05em;
      }

      .role-admin {
        background-color: #ef4444;
        color: white;
      }

      .role-manager {
        background-color: #f59e0b;
        color: #1e293b;
      }

      .role-staff {
        background-color: #3b82f6;
        color: white;
      }

      .sidenav-container {
        flex: 1;
        background-color: #f1f5f9;
      }

      .app-sidenav {
        width: 240px;
        background-color: #ffffff;
        border-right: 1px solid #e2e8f0;
      }

      .active-link {
        background-color: #eff6ff !important;
        color: #1d4ed8 !important;
        font-weight: 600;
      }

      .active-link mat-icon {
        color: #1d4ed8;
      }

      .nav-section-header {
        padding: 1rem 1rem 0.5rem;
        font-size: 0.7rem;
        font-weight: 700;
        text-transform: uppercase;
        color: #94a3b8;
        letter-spacing: 0.05em;
      }

      .main-content {
        display: flex;
        flex-direction: column;
        height: 100%;
        overflow-y: auto;
      }

      .content-wrapper {
        flex: 1;
        padding: 1.5rem;
        max-width: 1400px;
        width: 100%;
        margin: 0 auto;
      }

      /* Mobile bottom nav */
      .mobile-bottom-nav {
        display: none;
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        height: 56px;
        background-color: #ffffff;
        border-top: 1px solid #e2e8f0;
        z-index: 100;
        justify-content: space-around;
        align-items: center;
      }

      .bottom-nav-item {
        display: flex;
        flex-direction: column;
        align-items: center;
        text-decoration: none;
        color: #64748b;
        font-size: 0.75rem;
        gap: 2px;
      }

      .bottom-nav-item mat-icon {
        font-size: 20px;
        width: 20px;
        height: 20px;
      }

      .mobile-active {
        color: #2563eb;
        font-weight: 600;
      }

      @media (max-width: 768px) {
        .app-sidenav {
          display: none;
        }

        .menu-toggle-btn {
          display: none;
        }

        .mobile-bottom-nav {
          display: flex;
        }

        .content-wrapper {
          padding: 1rem;
          padding-bottom: 72px; /* space for bottom nav */
        }

        .user-name {
          display: none;
        }
      }
    `,
  ],
})
export class ShellComponent {
  readonly authService = inject(AuthService);
  private notificationService = inject(NotificationService);

  readonly currentUser = this.authService.currentUser;
  readonly unreadCount = this.notificationService.unreadCount;

  logout(): void {
    this.authService.logout(true).subscribe();
  }
}
