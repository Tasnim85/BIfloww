import { getServerSession } from "next-auth";
import { redirect } from "next/navigation";
import { Shell } from "@/components/app/Shell";
import { authOptions } from "@/lib/auth";
import { backendHealth } from "@/lib/backend";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const session = await getServerSession(authOptions);
  if (!session?.user?.id) redirect("/signin");
  const health = await backendHealth();
  return <Shell user={session.user} health={health}>{children}</Shell>;
}
