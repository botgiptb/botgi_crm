import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';

@Component({
  selector: 'app-leads-placeholder',
  standalone: true,
  imports: [CommonModule, MatCardModule, MatIconModule],
  template: `
    <mat-card>
      <mat-card-header>
        <mat-card-title>Leads Management</mat-card-title>
        <mat-card-subtitle>Phase 5a - Ready for Stop 2 (Lead List & Quick Add)</mat-card-subtitle>
      </mat-card-header>
      <mat-card-content style="padding: 2rem; text-align: center;">
        <mat-icon style="font-size: 64px; height: 64px; width: 64px; color: #3b82f6;">leaderboard</mat-icon>
        <h3 style="margin-top: 1rem;">Authentication & Application Shell Ready</h3>
        <p style="color: #64748b;">
          Session restored with httpOnly cookie rotation, reactive state, and notification polling.
        </p>
      </mat-card-content>
    </mat-card>
  `,
})
export class LeadsPlaceholderComponent {}
