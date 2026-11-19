import { Routes } from '@angular/router';
import { authGuard, managerGuard } from './core/auth/auth.guard';
import { LoginComponent } from './features/auth/login.component';
import { LeadListComponent } from './features/leads/lead-list.component';
import { LeadsPlaceholderComponent } from './features/leads/leads-placeholder.component';
import { ShellComponent } from './layout/shell.component';

export const routes: Routes = [
  {
    path: 'login',
    component: LoginComponent,
  },
  {
    path: '',
    component: ShellComponent,
    canActivate: [authGuard],
    children: [
      {
        path: '',
        pathMatch: 'full',
        redirectTo: 'leads',
      },
      {
        path: 'leads',
        component: LeadListComponent,
      },
      {
        path: 'leads/:id',
        component: LeadsPlaceholderComponent,
      },
      {
        path: 'notifications',
        component: LeadsPlaceholderComponent,
      },
      {
        path: 'unprocessed-meta-leads',
        component: LeadsPlaceholderComponent,
        canActivate: [managerGuard],
      },
    ],
  },
  {
    path: '**',
    redirectTo: 'leads',
  },
];
