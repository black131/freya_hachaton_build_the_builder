// Freya Bank mock (final case). The seven statement services of the 2026-10-01 service contract,
// POST https://<worker>/voice/v1/<service>, request {data:{...}, call:{...}}, answers {data, result}.
// Every answer for the bank's test customers comes from src/test-customers.json, with its HTTP status
// and delay, exactly as listed. Unknown customer / card / week: the contract's 404 for that service,
// or a 400 INVALID_ARGUMENTS_ERROR where the contract has no 404.
import DATA from "./test-customers.json";

const BASE = "/voice/v1/";
const CUSTOMERS = Object.fromEntries(DATA.customers.map(c => [String(c.customerNo), c]));
const FIRST = DATA.customers[0];

// service -> how the answer is found, which fields are required, the not-found answer
const SERVICES = {
  "cards.list":            { by: "customer", required: ["customerNo"],                     notFound: [404, "FB_IVR_CHANNEL_102", "Müşteriye ait geçerli kart bilgisi bulunamadı.", "WARNING"] },
  "cards.balance":         { by: "card",     required: ["cardNumber"],                     notFound: [404, "FB_IVR_CHANNEL_120", "Kart bakiye servisi hatası: kart bulunamadı", "WARNING"] },
  "statement.week.get":    { by: "card",     required: ["cardNumber"],                     notFound: [404, "FB_IVR_CHANNEL_121", "Ekstre haftası servisi hatası: kart bulunamadı", "WARNING"] },
  "statement.week.decide": { by: "week",     required: ["cardNumber", "newStatementWeek"], notFound: null },
  "statement.week.change": { by: "week",     required: ["cardNumber", "newStatementWeek"], notFound: null },
  "contact.email.get":     { by: "customer", required: ["customerNo", "intAddressInfoType"], notFound: null },
  "statement.pdf.send":    { by: "customer", required: ["customerNo", "cardNumber", "currencyType", "statementDate", "emailAddress"],
                             notFound: [404, "FB_IVR_CHANNEL_107", "Pdf dokümanı bulunamadı", "WARNING"] },
};
const FIELD_TEXT = { customerNo: "customer number", cardNumber: "card number", newStatementWeek: "newStatementWeek",
  intAddressInfoType: "intAddressInfoType", currencyType: "currency type", statementDate: "statement date", emailAddress: "email address" };

const CORS = { "access-control-allow-origin": "*" };
const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json; charset=utf-8", ...CORS } });

function guid() {
  const b = new Uint8Array(16); crypto.getRandomValues(b);
  return [...b].map(x => x.toString(16).padStart(2, "0")).join("");
}
function error(status, code, text, type) {
  const g = guid();
  return json(status, { result: { guid: g, returnCode: code, messageText: text, code, message: text, type,
    details: { guid: g, rootCause: type === "ERROR" ? "InvalidArgumentsException" : "NotFoundException", errorOrigin: "ivr-gateway-test:ivr-channel-v0" } } });
}
const invalid = text => error(400, "INVALID_ARGUMENTS_ERROR", text, "ERROR");
const notFound = svc => SERVICES[svc].notFound ? error(...SERVICES[svc].notFound) : invalid("record not found");

// The Freya panel's "Test API Request" sends variables unfilled, e.g. "{{customerNumber}}".
const isTemplate = v => typeof v === "string" && (v.includes("{{") || v.includes("%7B%7B"));
const text = v => (v === undefined || v === null) ? "" : String(v).trim();

async function answer(entry) {
  if (entry.delaySeconds) await new Promise(r => setTimeout(r, 1000 * Number(entry.delaySeconds)));
  return json(entry.http, entry.response);
}

async function service(name, request) {
  const svc = SERVICES[name];
  let body;
  try { body = await request.json(); } catch { return invalid("request body must be JSON"); }
  const data = (body && typeof body.data === "object" && body.data) ? body.data : {};
  const template = Object.values(data).some(isTemplate);
  if (!template) for (const f of svc.required) if (!text(data[f])) return invalid(`${FIELD_TEXT[f]} cannot be empty`);

  if (svc.by === "customer") {
    const customer = template ? FIRST : CUSTOMERS[text(data.customerNo)];
    const entry = customer && customer.services[name];
    return entry ? answer(entry) : notFound(name);
  }
  // card services: the masked number exactly as cards.list gave it
  const card = text(data.cardNumber);
  let table = null;
  for (const c of DATA.customers) {
    const t = c.services[name];
    if (t && (template ? Object.keys(t).length : t[card])) { table = template ? t[Object.keys(t)[0]] : t[card]; break; }
  }
  if (!table) return notFound(name);
  if (svc.by === "card") return answer(table);
  const week = template ? Object.keys(table)[0] : text(data.newStatementWeek);
  return table[week] ? answer(table[week]) : notFound(name);
}

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") return new Response(null, { headers: { ...CORS, "access-control-allow-methods": "GET, POST, OPTIONS", "access-control-allow-headers": "*" } });
    const path = url.pathname.replace(/\/+$/, "");
    if (request.method === "GET" && (path === "/health" || path === "")) {
      return json(200, { ok: true, customers: DATA.customers.length, services: Object.keys(SERVICES).map(s => "POST " + BASE + s) });
    }
    if (path.startsWith(BASE) && SERVICES[path.slice(BASE.length)]) {
      if (request.method !== "POST") return json(405, { error: "use POST" });
      return service(path.slice(BASE.length), request);
    }
    return json(404, { error: "not found", paths: Object.keys(SERVICES).map(s => "POST " + BASE + s) });
  },
};

// Kept so the earlier deployment's Durable Object binding stays valid; not used.
export class Bank { async fetch() { return json(404, {}); } }
