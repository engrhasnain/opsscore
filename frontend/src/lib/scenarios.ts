// The demo scenarios, one per pain point in "Oil & Gas and Maritime: pain-point research, US vs LATAM"
// (October 2026). Each scenario sends real events and messages to the OpsCore API.
// Opening figures are quoted from the research; its caveats apply (trade sources are indicative).

import type { ClientKey } from "./clients";

export type Action =
  | { type: "event"; body: { event_type: string; asset_code?: string; site_code?: string; attributes: Record<string, unknown>; description?: string } }
  | { type: "message"; sender: string; name: string; body: string; channel?: "whatsapp" | "sms" }
  | { type: "flood"; messages: { sender: string; name: string; body: string }[] }
  | { type: "ack" }
  | { type: "completeWork"; note: string; titleIncludes?: string }
  | { type: "resolve"; note: string }
  | { type: "replyEscalated"; to: string; body: string }
  | { type: "verify" };

export interface Step {
  label: string;
  detail: string;
  actions: Action[];
}

export interface Scenario {
  id: string;
  client: ClientKey;
  pain: string; // e.g. "O&G 1"
  painTitle: string;
  priority: "Lead with" | "Then" | "Context";
  title: string;
  summary: string;
  kind: "events" | "chat";
  opener: { figure: string; text: string; source: string; hypothesis?: boolean };
  say: string[];
  steps: Step[];
  close: string;
  /** From "What to validate in the first calls", where it applies to this scenario. */
  validate?: string;
}

/** Discovery questions from the research, per pain. Shown under every scenario of that pain. */
export const DISCOVERY: Record<string, string[]> = {
  "O&G 1": [
    "Where do incidents cluster: vehicles, struck-by, confined space?",
    "How do you supervise contractor crews at remote pads?",
    "How long does it take to compile evidence after an incident?",
  ],
  "O&G 2": [
    "How do you measure materials, pads and earthworks today?",
    "How often, and who signs off?",
    "How long between a request and a usable number?",
  ],
  "O&G 3": [
    "Who handles calls and messages from drivers and vendors at night and on weekends?",
    "How many are repeat status questions?",
    "What gets lost between a call and the system of record?",
  ],
  "Maritime 1": [
    "What happens on your phone lines during a strike or weather event?",
    "How many contacts are status questions?",
    "Which team absorbs the overflow?",
  ],
  "Maritime 2": [
    "Where do near-misses happen in the yard?",
    "How do you supervise night shifts?",
    "How do unions and workers view monitoring tools?",
  ],
  "Maritime 3": [
    "What compliance or reporting work falls on operations teams?",
    "Which disruption hurts most: strikes, weather or canal limits?",
  ],
};

const msg = (sender: string, name: string, body: string): Action => ({ type: "message", sender, name, body });

export const SCENARIOS: Scenario[] = [
  // ---------------------------------------------------------------- US oil & gas
  {
    id: "us-og-safety",
    client: "permian",
    pain: "O&G 1",
    painTitle: "Safety and compliance in remote, hazardous sites",
    priority: "Lead with",
    title: "Hazard at a remote pad: right person told, record ready",
    summary: "A flare flashback, a struck-by near miss and a vehicle incident at Permian Ridge, each routed to the right person with an audit-ready record.",
    kind: "events",
    opener: {
      figure: "489",
      text: "oil & gas extraction workers were killed on the job in 2013–2017. Vehicle crashes are the leading cause, and about 3 in 5 on-site deaths are struck-by, caught-in or caught-between. In September 2026 OSHA issued a hazard alert on flare flashback explosions at tank batteries.",
      source: "OSHA, Oil and Gas Extraction",
    },
    say: [
      "Your sensors, cameras and crews already see these events. The gap is the minutes between seeing and the right person acting, and the hours rebuilding what happened afterwards.",
      "Watch what happens to each event: who is told, on which channel, what work is opened, and what record is kept.",
    ],
    steps: [
      {
        label: "Flare flashback at tank battery 14-1",
        detail: "The exact hazard in OSHA's September 2026 alert. Critical: the safety lead gets SMS and email, and an urgent inspection is opened.",
        actions: [{ type: "event", body: { event_type: "flare_flashback", asset_code: "TB-14-1", attributes: { tank_battery: "TB-14-1" }, description: "Flame front observed returning into the flare line during load-out." } }],
      },
      {
        label: "Person 1 m from a reversing pipe truck",
        detail: "Struck-by, one of OSHA's leading fatality causes. Under 5 m it's critical: site supervisor and safety lead are told, and a stop-work order is opened.",
        actions: [{ type: "event", body: { event_type: "struck_by_hazard", site_code: "PAD-14", attributes: { zone: "Pipe rack", distance: 1 }, description: "Proximity camera: person in the path of a reversing pipe truck." } }],
      },
      {
        label: "Water truck rollover, driver hurt",
        detail: "Vehicle crashes are the leading cause of death. With injuries it's critical and goes to safety and operations at once.",
        actions: [{ type: "event", body: { event_type: "vehicle_incident", site_code: "PAD-22", attributes: { injuries: true, vehicle_id: "WT-118" }, description: "Water truck WT-118 rolled on lease road 3. Driver conscious, injured." } }],
      },
      {
        label: "Supervisor acknowledges and closes out",
        detail: "Each step is stamped with who and when, which is what an OSHA inquiry asks for.",
        actions: [
          { type: "ack" },
          { type: "completeWork", titleIncludes: "Inspect flare", note: "Flame arrestor replaced, flare line purged and re-lit under permit." },
          { type: "completeWork", titleIncludes: "Stop work", note: "Exclusion zone marked around the pipe rack, spotter rule re-briefed with the crew." },
          { type: "resolve", note: "Root cause and corrective actions recorded by EHS." },
        ],
      },
      {
        label: "Check the record can't have been edited",
        detail: "Every entry is chained by hash. One click proves nothing was changed after the fact.",
        actions: [{ type: "verify" }],
      },
    ],
    close: "Where do incidents cluster for you: vehicles, struck-by, confined space? How long does it take to compile evidence after one?",
  },
  {
    id: "us-og-after-hours",
    client: "permian",
    pain: "O&G 3",
    painTitle: "Workforce gap and manual, fragmented coordination",
    priority: "Then",
    title: "After-hours drivers answered instantly, only exceptions reach a person",
    summary: "Water and sand haulers message Permian Ridge at night in English and Spanish. Routine questions get the approved answer; an injury goes straight to on-call.",
    kind: "chat",
    opener: {
      figure: "~20%",
      text: "of the oil workforce was expected to retire by 2026, and 45% of oil & gas companies offer no AI training. Fewer experienced people are left to answer the same driver questions every night.",
      source: "PwC via trade summary (Cora Systems); secondary figures",
    },
    say: [
      "It answers only with what you approved, in the driver's language. Anything it can't answer, and any sign of danger, goes to your on-call person.",
      "Every conversation is logged, so nothing is lost between a call and your system of record.",
    ],
    steps: [
      { label: "After hours: a water hauler asks about pad hours", detail: "Approved answer, in seconds.", actions: [msg("+14325551201", "Mike · water hauler", "What time does pad 14 open?")] },
      { label: "Where does the run ticket go?", detail: "The repeat status question that eats a coordinator's evening.", actions: [msg("+14325551202", "Dwayne · water hauler", "Where do I drop the run ticket for my water haul?")] },
      { label: "Driver writes in Spanish", detail: "Detects the language and answers from the Spanish version.", actions: [msg("+14325551203", "José · sand hauler", "A que hora abre el pad 14?")] },
      { label: "A question nobody approved an answer for", detail: "It doesn't guess. It says a person will reply and alerts on-call.", actions: [msg("+14325551204", "Travis · pipe delivery", "Is there somewhere to sleep in the truck overnight?")] },
      { label: "Driver injured on a lease road", detail: "Danger words always go to a person, with a safety message to the driver.", actions: [msg("+14325551205", "Luis · water hauler", "Truck slid off the lease road near pad 22, driver is injured")] },
      { label: "Jordan replies from the console", detail: "A person takes over the conversation; the assistant stays quiet.", actions: [{ type: "replyEscalated", to: "Luis", body: "Jordan Hayes, Permian Ridge safety. Ambulance and a supervisor are on the way to lease road 3. Stay with the driver, hazards on." }] },
    ],
    close: "Who handles calls and messages from drivers and vendors at night and on weekends? How many are repeat status questions?",
  },
  // ---------------------------------------------------------------- LATAM oil & gas
  {
    id: "latam-og-assets",
    client: "andes",
    pain: "O&G 2",
    painTitle: "Visibility over remote assets and logistics",
    priority: "Lead with",
    title: "A yard measured and signed off in minutes, not days",
    summary: "Drone measurements of Andes Energy's material yard become numbers the operations manager signs off, and a wellhead fault reaches on-call.",
    kind: "events",
    opener: {
      figure: "$154M",
      text: "agreed by Neuquén and 13 companies for 166 km of road works. Vaca Muerta produces about 604k bbl/d and roads, pipelines and pads have not kept pace.",
      source: "Rio Times; Real Instituto Elcano",
    },
    say: [
      "When you're scaling fast, the question is not 'what happened' but 'where are we': how much sand is on site, which pad is ready.",
      "Each measurement lands as a number with an owner and a sign-off, instead of a spreadsheet three days later.",
    ],
    steps: [
      {
        label: "Drone survey: frac sand stockpile 1,240 m³",
        detail: "A measurement event from the survey becomes a sign-off task for the operations manager.",
        actions: [{ type: "event", body: { event_type: "material_measurement", asset_code: "SP-ARENA", attributes: { material: "frac sand", volume: 1240, measured_by: "Drone survey" }, description: "Survey flown 06:10, 312 images, volume ±2%." } }],
      },
      {
        label: "Gravel stockpile 860 m³",
        detail: "Same flow for the second stockpile.",
        actions: [{ type: "event", body: { event_type: "material_measurement", asset_code: "SP-GRAVA", attributes: { material: "gravel", volume: 860, measured_by: "Drone survey" }, description: "Same flight." } }],
      },
      {
        label: "Pad 12 earthworks: 18,400 m³ moved, 72% of design",
        detail: "Build-out progress, not just stock: the same survey reports how far the pad is, for the same sign-off.",
        actions: [{ type: "event", body: { event_type: "material_measurement", site_code: "PAD-12", attributes: { material: "movimiento de suelos", volume: 18400, measured_by: "Relevamiento con dron" }, description: "Avance de locación PAD-12: 72% del volumen de diseño. Camino de acceso km 0 a 4 terminado." } }],
      },
      {
        label: "Pressure fault on wellhead 7-3",
        detail: "A critical asset: on-call gets an SMS and a 4-hour work order is opened.",
        actions: [{ type: "event", body: { event_type: "equipment_fault", asset_code: "WH-07-3", attributes: { fault_code: "PT-221 high", pressure: 2850 }, description: "Casing pressure above setpoint for 10 minutes." } }],
      },
      {
        label: "Operations manager signs off the numbers",
        detail: "Ana Quiroga approves all three numbers; the record shows who signed what and when.",
        actions: [{ type: "completeWork", titleIncludes: "Aprobar", note: "Aprobado por Ana Quiroga: volúmenes conciliados con remitos y plan de obra." }],
      },
      { label: "Check the record", detail: "The hash chain proves the numbers were not edited later.", actions: [{ type: "verify" }] },
    ],
    close: "How do you measure materials, pads and earthworks today? How often, who signs off, and how long between a request and a usable number?",
    validate: "Who signs off on site measurements today, and what does it cost per site?",
  },
  {
    id: "latam-og-contractors",
    client: "andes",
    pain: "O&G 1",
    painTitle: "Safety and compliance in remote, hazardous sites",
    priority: "Then",
    title: "Contractor crews supervised, evidence ready for the insurer",
    summary: "PPE, struck-by and spill events from contractor crews at Andes Energy, routed by role, closed out, with a tamper-evident record.",
    kind: "events",
    opener: {
      figure: "Many crews",
      text: "Vaca Muerta operators are scaling a local contractor ecosystem after major foreign investors exited. The likely pain is supervising contractor crews across remote pads and proving what happened, for the operator and the insurer.",
      source: "Real Instituto Elcano; research hypothesis to validate in discovery",
      hypothesis: true,
    },
    say: ["Each event names the contractor and crew, reaches your site supervisor on WhatsApp, and becomes evidence you can hand to the operator or the insurer."],
    steps: [
      {
        label: "Contractor crew without hard hat at wellhead 7-3",
        detail: "PPE violation: the site supervisor is told on WhatsApp.",
        actions: [{ type: "event", body: { event_type: "ppe_violation", site_code: "PAD-07", attributes: { missing_item: "hard_hat", zone: "Boca de pozo 7-3" }, description: "Contratista: Servicios Patagonia SRL, cuadrilla 4. Cámara 2." } }],
      },
      {
        label: "Person 2 m from a mobile crane",
        detail: "Struck-by under 5 m is critical: stop-work order opened.",
        actions: [{ type: "event", body: { event_type: "struck_by_hazard", site_code: "PAD-12", attributes: { zone: "Zona de maniobra", distance: 2 }, description: "Contratista: Transportes del Sur, grúa móvil." } }],
      },
      {
        label: "2 bbl produced-water spill",
        detail: "Safety and environmental leads are told, and a containment order is opened.",
        actions: [{ type: "event", body: { event_type: "spill", site_code: "PAD-07", attributes: { volume: 2, substance: "agua de producción" }, description: "Derrame contenido en pileta. Contratista: Servicios Patagonia SRL." } }],
      },
      {
        label: "Close out with corrective actions",
        detail: "Acknowledged, work done, resolved, each with who and when.",
        actions: [
          { type: "ack" },
          { type: "completeWork", titleIncludes: "Detener tareas", note: "Cuadrilla 4 suspendida hasta re-inducción. Zona de maniobra señalizada." },
          { type: "completeWork", titleIncludes: "derrame", note: "Derrame recuperado con camión de vacío; suelo afectado retirado a repositorio." },
          { type: "resolve", note: "Acciones correctivas cumplidas. Evidencia enviada al operador y a la aseguradora." },
        ],
      },
      { label: "Check the record", detail: "Proof for the operator and the insurer that nothing was changed.", actions: [{ type: "verify" }] },
    ],
    close: "How do you supervise contractor crews at remote pads? Is that pain yours, or owned by the contractors and insurers?",
    validate: "Does safety pain exist at the operator level, or is it owned by contractors and insurers?",
  },
  // ---------------------------------------------------------------- LATAM maritime
  {
    id: "latam-port-disruption",
    client: "atlantico",
    pain: "Maritime 1",
    painTitle: "Port congestion and schedule unreliability",
    priority: "Lead with",
    title: "Strike day: dozens of truckers answered at once",
    summary: "A strike closes gate 1 at Terminal Atlântico. The queue builds, truckers flood WhatsApp in Portuguese, Spanish and English, and only real exceptions reach the team.",
    kind: "chat",
    opener: {
      figure: "~3.5 days",
      text: "average wait at Santos during the May 2026 dock strike across 32 Brazilian ports. Panama Canal queues peaked at 161 vessels in August 2026, with waits beyond 11 days.",
      source: "Everstream (other providers report shorter waits); Blooming Global",
    },
    say: [
      "On a day like this your phone lines are flooded with the same question: is the gate open, how long is the wait, can I rebook.",
      "The team posts the update once. The assistant answers everyone, in their language, and only the real exceptions reach a person.",
    ],
    steps: [
      {
        label: "Strike declared: gate 1 closed, vessel delayed",
        detail: "Operations and customer service are told; the gate closure and the 14-hour vessel delay raise their own alerts.",
        actions: [
          { type: "event", body: { event_type: "strike_disruption", site_code: "GATE-1", attributes: { scope: "Paralisação de portuários", expected_hours: 12 }, description: "Sindicato confirmou paralisação a partir das 06h." } },
          { type: "event", body: { event_type: "gate_status", site_code: "GATE-1", attributes: { gate: "Portão 1", status: "closed", reason: "Greve" } } },
          { type: "event", body: { event_type: "vessel_delay", site_code: "BERCO-3", attributes: { vessel: "Maersk Santos", delay_hours: 14, berth: "Berço 3" }, description: "Atracação adiada pela paralisação." } },
        ],
      },
      {
        label: "Queue at gate 2 passes 3 hours",
        detail: "Over 2 hours triggers a WhatsApp to the operations supervisor.",
        actions: [{ type: "event", body: { event_type: "truck_queue", site_code: "GATE-2", attributes: { gate: "Portão 2", wait_minutes: 185, trucks: 140 } } }],
      },
      {
        label: "28 truckers message at once",
        detail: "Gate status, ETA and rebooking, in Portuguese, Spanish and English. Each gets the approved answer in seconds.",
        actions: [
          {
            type: "flood",
            messages: [
              ["+5513981110001", "Carlos · Transportes Rocha", "Bom dia, o portão 1 está aberto hoje?"],
              ["+5513981110002", "Marcos", "Qual a situação da fila agora?"],
              ["+5513981110003", "Adriana · RodoSul", "Perdi minha janela por causa da greve, como reagendar?"],
              ["+5513981110004", "Fábio", "Que documentos preciso para retirar o contêiner?"],
              ["+5513981110005", "Renato", "Onde devolvo o vazio?"],
              ["+5951812220006", "Hugo · Asunción", "Hola, el porton esta abierto hoy?"],
              ["+5513981110007", "Wagner", "O portão 2 está com muita fila?"],
              ["+5513981110008", "Diego", "Tem greve hoje? Posso entrar pelo portão 1?"],
              ["+5513981110009", "Patrícia · LogMar", "Minha janela era 8h, perdi. Como remarcar?"],
              ["+5513981110010", "Sérgio", "Quanto tempo de espera no portão hoje?"],
              ["+5491123330011", "Martín · Buenos Aires", "Cual es el estado del porton ahora? hay mucha fila?"],
              ["+15045440012", "Mike · forwarder", "Is the gate open today?"],
              ["+5513981110013", "Roberto", "Preciso de quais documentos para retirada de importação?"],
              ["+5513981110014", "Luana", "Onde entregar o contêiner vazio?"],
              ["+5513981110015", "Jefferson", "O portão está fechado por causa da greve?"],
              ["+5513981110016", "André · TransBrasil", "Perdi o agendamento, consigo reagendar sem custo?"],
              ["+5513981110017", "Cláudio", "Qual a previsão de atracação do Maersk Santos?"],
              ["+5598122110018", "Rubén · Montevideo", "Hola, hay paro? el porton esta cerrado?"],
              ["+5513981110019", "Thiago", "Qual portão está aberto hoje?"],
              ["+5513981110020", "Simone", "Onde devolvo vazio de 40 pés?"],
              ["+5513981110021", "Gustavo", "Quando o navio chega no berço 3?"],
              ["+5513981110022", "Paulo", "A fila do portão 2 está andando?"],
              ["+5513981110023", "Ricardo · Expresso Sul", "Perdi minha janela, como faço para reagendar?"],
              ["+5513981110024", "Eduardo", "O portão 1 abre hoje?"],
              ["+15045440025", "Sarah · forwarder", "What's the gate status now? Is there a strike?"],
              ["+5491123330026", "Leandro · Rosario", "Cuándo llega el buque Maersk Santos?"],
              ["+5513981110027", "Fernanda", "Onde é a devolução de vazios?"],
              ["+5513981110028", "Márcio", "Situação da fila agora, por favor"],
            ].map(([sender, name, body]) => ({ sender, name, body })),
          },
        ],
      },
      {
        label: "Two messages that need a person",
        detail: "An accident in the queue and a request for an agent. Both reach the team; the assistant does not improvise.",
        actions: [
          msg("+5513981110031", "Vítor", "Acidente na fila do portão 2, motorista ferido"),
          msg("+5513981110032", "Juliana · Agro Exportadora", "Quero falar com um atendente sobre minha carga retida"),
        ],
      },
      { label: "The team takes over one conversation", detail: "Rafael replies from the console; the trucker sees it on WhatsApp.", actions: [{ type: "replyEscalated", to: "Vítor", body: "Rafael, operações do Terminal Atlântico. Ambulância e segurança a caminho do portão 2. Fique no local, por favor." }] },
    ],
    close: "What happens on your phone lines during a strike or weather event? How many contacts are status questions? Which team absorbs the overflow?",
    validate: "Which contact volumes (drivers, truckers, forwarders) are handled by phone and which by WhatsApp?",
  },
  {
    id: "latam-port-yard",
    client: "atlantico",
    pain: "Maritime 2",
    painTitle: "Labor shortage, automation tension and yard safety",
    priority: "Then",
    title: "Night shift in the yard: near misses reach the supervisor",
    summary: "Patio B at Terminal Atlântico runs through the night with trucks, reach stackers and people in the same lanes. Two near misses and a wind warning reach the yard supervisor in Portuguese, and each one gets a follow-up.",
    kind: "events",
    opener: {
      figure: "32 ports",
      text: "were stopped by a 12-hour dock strike in Brazil in May 2026, and Buenaventura was blockaded the same month. Terminals that grow this fast need safety oversight without adding supervisors.",
      source: "Everstream; regional press. Research hypothesis to validate in discovery",
      hypothesis: true,
    },
    say: [
      "Patio B never stops. Your yard supervisor can't watch every lane on a night shift.",
      "Each near miss reaches the supervisor in seconds, in Portuguese, and the follow-up stays open until someone closes it.",
    ],
    steps: [
      {
        label: "Night shift: a trucker steps out of his cab beside a reach stacker",
        detail: "Yard near miss: the yard supervisor gets an SMS and a review order is opened for quadra 2.",
        actions: [{ type: "event", body: { event_type: "yard_near_miss", asset_code: "RS-21", attributes: { zone: "Quadra 2", equipment: "Empilhadeira RS-21", people_involved: 1 }, description: "Motorista desceu do caminhão na quadra 2; a RS-21 parou a 3 m. Câmera 7." } }],
      },
      {
        label: "A checker crosses a terminal tractor lane",
        detail: "A second near miss in another quadra becomes its own alert and its own follow-up.",
        actions: [{ type: "event", body: { event_type: "yard_near_miss", asset_code: "TT-08", attributes: { zone: "Quadra 4", equipment: "Caminhão de pátio TT-08", people_involved: 1 }, description: "Conferente atravessou a faixa de tráfego fora da passarela." } }],
      },
      {
        label: "Wind gusts of 38 kn at berth 3",
        detail: "Over 35 kn: operations and the yard supervisor are told and a 'secure cranes' order is opened.",
        actions: [{ type: "event", body: { event_type: "weather_alert", site_code: "BERCO-3", attributes: { condition: "Rajadas de vento", wind_speed: 38 } } }],
      },
      {
        label: "The supervisor closes the loop",
        detail: "Acknowledged, each follow-up done with what was changed, then resolved.",
        actions: [
          { type: "ack" },
          { type: "completeWork", titleIncludes: "Quadra 2", note: "Motoristas orientados a não descer da cabine no pátio. Sinalização reforçada na quadra 2." },
          { type: "completeWork", titleIncludes: "Quadra 4", note: "Passarela de pedestres repintada; conferentes reorientados no turno da manhã." },
          { type: "completeWork", titleIncludes: "Travar", note: "Portêiner 2 travado e pilhas amarradas antes da rajada." },
          { type: "resolve", note: "Ações corretivas concluídas e registradas pelo supervisor de pátio." },
        ],
      },
      { label: "Check the record", detail: "One record the terminal, the union and the insurer can all rely on.", actions: [{ type: "verify" }] },
    ],
    close: "Where do near misses happen in your yard, and how do you supervise the night shift today?",
  },
  // ---------------------------------------------------------------- US maritime
  {
    id: "us-port-yard-safety",
    client: "bayou",
    pain: "Maritime 2",
    painTitle: "Labor shortage, automation tension and yard safety",
    priority: "Lead with",
    title: "Yard near-miss flagged to the supervisor in real time",
    summary: "At Bayou Container Terminal a straddle carrier stops 2 m from a lasher, a squall line approaches and the gate queue builds. Supervisors get the facts, not a robot.",
    kind: "events",
    opener: {
      figure: "47,000",
      text: "workers at 36 East and Gulf Coast ports struck in 2024, the first such strike since 1977, with automation at its core. Technology that helps supervisors protect workers lands better than technology that replaces them.",
      source: "2024 US port strike coverage; Moody's via World Ports",
    },
    say: ["Nothing here replaces anyone. It makes sure the yard supervisor knows about a near miss in seconds, and that the follow-up actually happens."],
    steps: [
      {
        label: "Straddle carrier stops 2 m from a lasher",
        detail: "Yard near-miss: the yard supervisor gets an SMS and a 24-hour review is opened.",
        actions: [{ type: "event", body: { event_type: "yard_near_miss", site_code: "YARD-3", attributes: { zone: "Row E", equipment: "Straddle carrier SC-17", people_involved: 1 }, description: "Lasher stepped into the travel lane; SC-17 stopped 2 m away." } }],
      },
      {
        label: "Squall line, 42 kn gusts at berth 2",
        detail: "Over 35 kn: operations and the yard supervisor are told, and a 'secure cranes' order is opened.",
        actions: [{ type: "event", body: { event_type: "weather_alert", site_code: "BERTH-2", attributes: { condition: "Squall line", wind_speed: 42 } } }],
      },
      {
        label: "Gate A wait passes 2 hours",
        detail: "Congestion reaches the operations supervisor on WhatsApp.",
        actions: [{ type: "event", body: { event_type: "truck_queue", site_code: "GATE-A", attributes: { gate: "Gate A", wait_minutes: 135, trucks: 64 } } }],
      },
      {
        label: "Supervisors close the loop",
        detail: "Acknowledged, actions recorded, resolved.",
        actions: [
          { type: "ack" },
          { type: "completeWork", titleIncludes: "Review near miss", note: "Lane markings repainted, toolbox talk held with the lashing gang." },
          { type: "completeWork", titleIncludes: "Secure cranes", note: "Cranes pinned and stacks lashed before the squall arrived. All clear." },
          { type: "resolve", note: "Corrective actions done and briefed to the night shift." },
        ],
      },
      { label: "Check the record", detail: "A record the safety committee and the union can both trust.", actions: [{ type: "verify" }] },
    ],
    close: "Where do near-misses happen in your yard? How do you supervise night shifts? How do your crews and the union view monitoring tools?",
    validate: "Is automation a live topic or a sensitive one with this buyer?",
  },
  {
    id: "us-port-congestion",
    client: "bayou",
    pain: "Maritime 1",
    painTitle: "Port congestion and schedule unreliability",
    priority: "Then",
    title: "Surge day: truckers and forwarders answered without tying up the team",
    summary: "An import surge and a weather-held vessel at Bayou Container Terminal. The gate queue grows, truckers and forwarders write in English and Spanish, and only two messages need a person.",
    kind: "chat",
    opener: {
      figure: "up to 40%",
      text: "less truck waiting is reported where gate automation runs with appointment scheduling. Tariff front-loading and seasonal surges are testing US gateways, and importers are moving cargo toward Gulf and East Coast ports.",
      source: "Port automation trade reporting (Globalia); Moody's via World Ports",
    },
    say: [
      "In the US, congestion comes in episodes: a tariff deadline, a weather hold, a surge. On those days gate staff and customer service spend the shift answering the same five questions.",
      "Post the update once. Every trucker and forwarder gets it in seconds, and your team only handles what actually needs a person.",
    ],
    steps: [
      {
        label: "Import surge: gate A wait passes 2 hours, gate B closed",
        detail: "The operations supervisor hears about the queue on WhatsApp; the gate closure raises its own alert.",
        actions: [
          { type: "event", body: { event_type: "truck_queue", site_code: "GATE-A", attributes: { gate: "Gate A", wait_minutes: 140, trucks: 88 } } },
          { type: "event", body: { event_type: "gate_status", site_code: "GATE-B", attributes: { gate: "Gate B", status: "closed", reason: "Lane repair until 2:00 PM" } } },
        ],
      },
      {
        label: "MSC Aurora held 20 hours by weather",
        detail: "Over six hours: operations and customer service are told before the calls start.",
        actions: [{ type: "event", body: { event_type: "vessel_delay", site_code: "BERTH-2", attributes: { vessel: "MSC Aurora", delay_hours: 20, berth: "Berth 2" }, description: "Pilot boarding suspended overnight for fog and wind." } }],
      },
      {
        label: "18 truckers and forwarders write in at once",
        detail: "Gate status, vessel ETA, rebooking, empties and paperwork, in English and Spanish. Each gets the approved answer.",
        actions: [
          {
            type: "flood",
            messages: [
              ["+15045551301", "Darnell · drayage", "Is gate B still closed?"],
              ["+15045551302", "Mike · Gulf Freight", "How long is the line at gate A right now?"],
              ["+15045551303", "Tasha · forwarder", "When is the MSC Aurora arriving?"],
              ["+15045551304", "Kevin", "I missed my 10am appointment because of the line, can I rebook?"],
              ["+15045551305", "Jorge", "Cuál es la espera en el portón hoy?"],
              ["+15045551306", "Ray · RTX Trucking", "Where do I drop empties?"],
              ["+15045551307", "Amanda · importer", "Is my container off the Aurora available today?"],
              ["+15045551308", "Curtis", "What documents do I need to pick up an import?"],
              ["+15045551309", "Pedro", "Cuándo llega el buque Aurora?"],
              ["+15045551310", "Shawn", "Is there a delay at gate A?"],
              ["+15045551311", "Lisa · forwarder", "What's the ETA on the vessel at berth 2?"],
              ["+15045551312", "Brandon", "Need to reschedule my slot, how do I do that?"],
              ["+15045551313", "Miguel", "El portón B está cerrado?"],
              ["+15045551314", "Terrence", "Do I need my TWIC card for pickup?"],
              ["+15045551315", "Gary", "What are the gate hours on Saturday?"],
              ["+15045551316", "Nicole · customs broker", "What's the gate status right now?"],
              ["+15045551317", "Andre", "Where do I return an empty container?"],
              ["+15045551318", "Luis · drayage", "Are you open Saturday?"],
            ].map(([sender, name, body]) => ({ sender, name, body })),
          },
        ],
      },
      {
        label: "Two messages that need a person",
        detail: "A demurrage dispute and an injury in the gate lane. Both reach the team; the assistant does not improvise.",
        actions: [
          msg("+15045551321", "Keisha · forwarder", "I need to talk to someone about demurrage on my container, the ship was late"),
          msg("+15045551322", "Wade · drayage", "Chassis tipped over in the gate A lane, driver is hurt"),
        ],
      },
      { label: "The team takes over one conversation", detail: "Marcus replies from the console; the forwarder sees it on WhatsApp.", actions: [{ type: "replyEscalated", to: "Keisha", body: "Marcus at Bayou Container Terminal. Weather holds on the MSC Aurora qualify for extra free time; I've added two days to your container. Confirmation is on its way by email." }] },
    ],
    close: "What happens on your phone lines during a surge or a weather hold? How many of those contacts are status questions, and which team absorbs the overflow?",
  },
  {
    id: "us-port-records",
    client: "bayou",
    pain: "Maritime 3",
    painTitle: "Regulatory, emissions, cyber and geopolitical pressure",
    priority: "Context",
    title: "A cyber incident handled with an audit-ready record",
    summary: "Short, for executives: the gate system is isolated after suspicious logins, the security lead is told at once, and the response is documented end to end.",
    kind: "events",
    opener: {
      figure: ">$1M",
      text: "estimated average cost of a cyberattack on a shipping company. Maritime cyber rules push ports toward incident response plans and audit trails.",
      source: "LMITAC; Maritime Gateway (trade estimates)",
    },
    say: ["This one is about showing you understand the regulatory pressure: every action in a disruption is documented, timestamped and provably unedited."],
    steps: [
      {
        label: "Suspicious logins on the gate OCR system",
        detail: "Cyber incident: critical, security lead by SMS and email.",
        actions: [{ type: "event", body: { event_type: "cyber_incident", site_code: "GATE-A", attributes: { system: "Gate OCR and appointment system" }, description: "Logins from an unknown IP at 03:12. System isolated by IT." } }],
      },
      {
        label: "Respond and close",
        detail: "Acknowledged and resolved with the response recorded.",
        actions: [{ type: "ack" }, { type: "resolve", note: "Credentials rotated, OCR back online 05:40. Report filed." }],
      },
      { label: "Produce the evidence", detail: "The full timeline with a verified hash chain.", actions: [{ type: "verify" }] },
    ],
    close: "What compliance or reporting work falls on your operations team? Which disruption hurts most: strikes, weather or canal limits?",
  },
];

export const MARKETS: { key: ClientKey; lead: string; then: string; skip: string }[] = [
  { key: "permian", lead: "Pain 1 · safety / compliance", then: "Pain 3 · workforce / coordination", skip: "Pain 2 unless asset data is the stated issue" },
  { key: "andes", lead: "Pain 2 · assets / logistics", then: "Pain 1 · contractor oversight", skip: "Pain 3 until validated" },
  { key: "bayou", lead: "Pain 2 · labor / automation / safety", then: "Pain 1 · congestion", skip: "Pain 3 as a demo (use as context)" },
  { key: "atlantico", lead: "Pain 1 · congestion", then: "Pain 2 · yard safety", skip: "Pain 3 as a demo (use as context)" },
];

export function scenario(id: string): Scenario | undefined {
  return SCENARIOS.find((s) => s.id === id);
}
