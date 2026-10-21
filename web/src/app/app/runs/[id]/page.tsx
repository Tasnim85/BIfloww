import { RunView } from "@/components/run/RunView";

type Props = { params: Promise<{ id: string }>; searchParams: Promise<{ new?: string }> };

export const metadata = { title: "Analysis" };

export default async function Page({ params, searchParams }: Props) {
  const { id } = await params;
  const { new: isNew } = await searchParams;
  return <RunView id={id} isNew={isNew === "1"} />;
}
