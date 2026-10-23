// Throwaway sign-in for the isolated e2e stack. Matches the defaults in
// scripts/seed_e2e_user.py; never a real account.
export const E2E_USER = process.env.E2E_USER || 'e2e-admin';
export const E2E_PASSWORD = process.env.E2E_PASSWORD || 'e2e-password-1234';
