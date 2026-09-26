export const SERVER =
  (import.meta.env.VITE_SERVER_URL as string | undefined) ?? "localhost:8000";
