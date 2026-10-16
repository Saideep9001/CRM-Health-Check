/**
 * Whether the app requires sign-in. Off by default: every page opens directly.
 * Set VITE_AUTH_REQUIRED=true to enforce the login page (/login) and route guard.
 */
export const AUTH_REQUIRED = import.meta.env.VITE_AUTH_REQUIRED === 'true';

/** Where "enter the app" calls to action point. */
export const APP_ENTRY_PATH = AUTH_REQUIRED ? '/login' : '/dashboard';
