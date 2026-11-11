import { Routes } from '@angular/router';

export const routes: Routes = [
  {
    path: 'app',
    loadComponent: () =>
      import('./dashboard/dashboard.component').then((m) => m.DashboardComponent),
  },
  {
    path: 'login',
    loadComponent: () => import('./auth/auth.component').then((m) => m.AuthComponent),
  },
  {
    path: 'register',
    loadComponent: () => import('./auth/auth.component').then((m) => m.AuthComponent),
  },
  { path: 'recover', redirectTo: 'forgot-password' },
  {
    path: 'forgot-password',
    loadComponent: () => import('./auth/auth.component').then((m) => m.AuthComponent),
  },
  {
    path: 'reset-password',
    loadComponent: () => import('./auth/auth.component').then((m) => m.AuthComponent),
  },
  {
    path: 'confirm-email',
    loadComponent: () => import('./auth/auth.component').then((m) => m.AuthComponent),
  },
  {
    path: '**',
    loadComponent: () => import('./public/public.component').then((m) => m.PublicComponent),
  },
];
