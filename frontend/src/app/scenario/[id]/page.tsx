import { notFound } from "next/navigation";
import { ScenarioRunner } from "@/components/ScenarioRunner";
import { scenario, SCENARIOS } from "@/lib/scenarios";

export function generateStaticParams() {
  return SCENARIOS.map((s) => ({ id: s.id }));
}

export default async function ScenarioPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const sc = scenario(id);
  if (!sc) notFound();
  return <ScenarioRunner id={sc.id} />;
}
