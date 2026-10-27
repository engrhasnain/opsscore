// The four demo clients created by `python -m app.cli seed-demo` (backend/app/demo_seed.py).

export type ClientKey = "permian" | "andes" | "bayou" | "atlantico";
export type Market = "us-og" | "latam-og" | "us-port" | "latam-port";

export interface DemoClient {
  key: ClientKey;
  name: string;
  email: string;
  market: Market;
  marketLabel: string;
  industry: "Oil & Gas" | "Maritime";
  region: "US" | "LATAM";
  language: string;
  place: string;
  /** The client's own time zone (matches the seeded organization); times on screen use it. */
  timeZone: string;
}

export const CLIENTS: Record<ClientKey, DemoClient> = {
  permian: {
    key: "permian",
    name: "Permian Ridge Operating",
    email: "owner@permian.demo",
    market: "us-og",
    marketLabel: "US oil & gas",
    industry: "Oil & Gas",
    region: "US",
    language: "English · Spanish",
    place: "Midland Basin, Texas",
    timeZone: "America/Chicago",
  },
  andes: {
    key: "andes",
    name: "Andes Energy",
    email: "owner@andes.demo",
    market: "latam-og",
    marketLabel: "LATAM oil & gas",
    industry: "Oil & Gas",
    region: "LATAM",
    language: "Spanish · English",
    place: "Neuquén, Argentina",
    timeZone: "America/Argentina/Buenos_Aires",
  },
  bayou: {
    key: "bayou",
    name: "Bayou Container Terminal",
    email: "owner@bayou.demo",
    market: "us-port",
    marketLabel: "US maritime",
    industry: "Maritime",
    region: "US",
    language: "English · Spanish",
    place: "Gulf Coast",
    timeZone: "America/Chicago",
  },
  atlantico: {
    key: "atlantico",
    name: "Terminal Atlântico",
    email: "owner@atlantico.demo",
    market: "latam-port",
    marketLabel: "LATAM maritime",
    industry: "Maritime",
    region: "LATAM",
    language: "Portuguese · Spanish · English",
    place: "São Paulo coast, Brazil",
    timeZone: "America/Sao_Paulo",
  },
};

export const CLIENT_KEYS = Object.keys(CLIENTS) as ClientKey[];

export function isClientKey(value: string): value is ClientKey {
  return value in CLIENTS;
}
