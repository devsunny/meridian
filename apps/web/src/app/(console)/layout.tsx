import { AppShell, RequireAuth } from "@/components/AppShell";

export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  return (
    <RequireAuth>
      <AppShell>{children}</AppShell>
    </RequireAuth>
  );
}
