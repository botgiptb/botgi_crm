import { CommonModule } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { AuthService } from '../../core/auth/auth.service';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatIconModule,
    MatProgressBarModule,
  ],
  template: `
    <div class="login-container">
      <mat-card class="login-card">
        <mat-card-header>
          <div class="header-content">
            <mat-icon class="crm-logo-icon">computer</mat-icon>
            <mat-card-title>Shop CRM</mat-card-title>
            <mat-card-subtitle>Computer Sales & Lead Management</mat-card-subtitle>
          </div>
        </mat-card-header>

        @if (isLoading()) {
          <mat-progress-bar mode="indeterminate"></mat-progress-bar>
        }

        <mat-card-content>
          @if (authService.isOffline()) {
            <div class="alert-box alert-warning">
              <mat-icon>cloud_off</mat-icon>
              <span>Cannot connect to CRM backend. Please check your network connection.</span>
            </div>
          }

          @if (errorMessage()) {
            <div class="alert-box alert-error">
              <mat-icon>error_outline</mat-icon>
              <span>{{ errorMessage() }}</span>
            </div>
          }

          <form [formGroup]="loginForm" (ngSubmit)="onSubmit()">
            <mat-form-field appearance="outline" class="full-width">
              <mat-label>Username or Email</mat-label>
              <input
                matInput
                formControlName="username"
                placeholder="e.g. staff1 or admin"
                autocomplete="username"
              />
              <mat-icon matPrefix>person</mat-icon>
              @if (loginForm.get('username')?.hasError('required') && loginForm.get('username')?.touched) {
                <mat-error>Username is required</mat-error>
              }
            </mat-form-field>

            <mat-form-field appearance="outline" class="full-width">
              <mat-label>Password</mat-label>
              <input
                matInput
                [type]="hidePassword() ? 'password' : 'text'"
                formControlName="password"
                placeholder="Enter password"
                autocomplete="current-password"
              />
              <mat-icon matPrefix>lock</mat-icon>
              <button
                mat-icon-button
                matSuffix
                type="button"
                (click)="hidePassword.set(!hidePassword())"
                [attr.aria-label]="'Hide password'"
                [attr.aria-pressed]="hidePassword()"
              >
                <mat-icon>{{ hidePassword() ? 'visibility_off' : 'visibility' }}</mat-icon>
              </button>
              @if (loginForm.get('password')?.hasError('required') && loginForm.get('password')?.touched) {
                <mat-error>Password is required</mat-error>
              }
            </mat-form-field>

            <button
              mat-flat-button
              color="primary"
              class="full-width login-btn"
              type="submit"
              [disabled]="loginForm.invalid || isLoading()"
            >
              Sign In
            </button>
          </form>
        </mat-card-content>

        <mat-card-footer class="login-footer">
          <small>Protected by secure session cookies and IP rate limiting</small>
        </mat-card-footer>
      </mat-card>
    </div>
  `,
  styles: [
    `
      .login-container {
        display: flex;
        justify-content: center;
        align-items: center;
        min-height: 100vh;
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
        padding: 1rem;
      }

      .login-card {
        width: 100%;
        max-width: 420px;
        border-radius: 12px;
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3), 0 8px 10px -6px rgba(0, 0, 0, 0.2);
        overflow: hidden;
      }

      mat-card-header {
        display: flex;
        justify-content: center;
        padding: 2rem 1.5rem 1rem;
      }

      .header-content {
        text-align: center;
      }

      .crm-logo-icon {
        font-size: 48px;
        height: 48px;
        width: 48px;
        color: #3b82f6;
        margin-bottom: 0.5rem;
      }

      mat-card-title {
        font-size: 1.5rem;
        font-weight: 700;
        letter-spacing: -0.025em;
      }

      mat-card-subtitle {
        color: #64748b;
        margin-top: 0.25rem;
      }

      mat-card-content {
        padding: 1.5rem;
      }

      .alert-box {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        padding: 0.75rem 1rem;
        border-radius: 8px;
        margin-bottom: 1.25rem;
        font-size: 0.875rem;
      }

      .alert-error {
        background-color: #fef2f2;
        color: #991b1b;
        border: 1px solid #fecaca;
      }

      .alert-warning {
        background-color: #fffbeb;
        color: #92400e;
        border: 1px solid #fde68a;
      }

      .full-width {
        width: 100%;
        margin-bottom: 0.75rem;
      }

      .login-btn {
        height: 48px;
        font-size: 1rem;
        font-weight: 500;
        margin-top: 0.5rem;
      }

      .login-footer {
        padding: 1rem 1.5rem;
        text-align: center;
        color: #94a3b8;
        border-top: 1px solid #f1f5f9;
      }
    `,
  ],
})
export class LoginComponent {
  private fb = inject(FormBuilder);
  private router = inject(Router);
  private route = inject(ActivatedRoute);
  readonly authService = inject(AuthService);

  readonly isLoading = signal(false);
  readonly errorMessage = signal<string | null>(null);
  readonly hidePassword = signal(true);

  readonly loginForm = this.fb.group({
    username: ['', [Validators.required]],
    password: ['', [Validators.required]],
  });

  onSubmit(): void {
    if (this.loginForm.invalid) {
      this.loginForm.markAllAsTouched();
      return;
    }

    const { username, password } = this.loginForm.value;
    if (!username || !password) return;

    this.isLoading.set(true);
    this.errorMessage.set(null);

    this.authService
      .login({ username, password })
      .subscribe({
        next: () => {
          this.isLoading.set(false);
          const returnUrl = this.route.snapshot.queryParams['returnUrl'] || '/leads';
          this.router.navigateByUrl(returnUrl);
        },
        error: (err) => {
          this.isLoading.set(false);
          if (err.status === 429) {
            this.errorMessage.set(
              err.error?.detail || 'Too many failed login attempts. Please wait 1 minute before trying again.'
            );
          } else if (err.status === 401) {
            this.errorMessage.set(err.error?.detail || 'Invalid username or password.');
          } else if (err.status === 0) {
            this.errorMessage.set('Cannot reach CRM server. Check your connection.');
          } else {
            this.errorMessage.set(err.error?.detail || 'An unexpected error occurred. Please try again.');
          }
        },
      });
  }
}
