import { notFound } from "next/navigation";
import { IncidentRecord } from "@/components/IncidentRecord";
import { isClientKey } from "@/lib/clients";

export default async function RecordPage({ params }: { params: Promise<{ client: string; alertId: string }> }) {
  const { client, alertId } = await params;
  if (!isClientKey(client) || !/^[\w-]+$/.test(alertId)) notFound();
  return <IncidentRecord client={client} alertId={alertId} />;
}
