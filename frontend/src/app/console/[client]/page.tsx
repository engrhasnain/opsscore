import { notFound } from "next/navigation";
import { Console } from "@/components/Console";
import { CLIENT_KEYS, isClientKey } from "@/lib/clients";

export function generateStaticParams() {
  return CLIENT_KEYS.map((client) => ({ client }));
}

export default async function ConsolePage({ params }: { params: Promise<{ client: string }> }) {
  const { client } = await params;
  if (!isClientKey(client)) notFound();
  return <Console client={client} />;
}
