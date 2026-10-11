// Mock bank for the case. Written from the case's service contract and test customers.
// One Durable Object holds every record, so a write is seen by the next read at once.
// CONTRACT-SPECIFIC PARTS are marked: the customer list and the operations.

// ---- CONTRACT-SPECIFIC: test customers (from the case's test customer file) ----
const CUSTOMERS = {
  // "c_001": { first_name: "Ayşe", last_name: "Yılmaz", birth_date: "1985-04-12", products: [...] },
};

// ---- CONTRACT-SPECIFIC: operations. Each gets (body, customer, state) and returns [status, json].
// state is this customer's record; change it and it is saved after the call.
const OPS = {
  // async verify_identity(body, c, st) { ... return [200, { verified: true }]; },
};

const json = (status, obj) => new Response(JSON.stringify(obj), {
  status, headers: { "content-type": "application/json; charset=utf-8", "access-control-allow-origin": "*" },
});

export class Bank {
  constructor(ctx) { this.ctx = ctx; }
  async fetch(request) {
    const url = new URL(request.url);
    const parts = url.pathname.replace(/\/+$/, "").split("/").filter(Boolean);   // ["v1", op, ...]
    if (parts[0] !== "v1") return json(404, { error: "not_found" });
    const op = parts[1] || "";
    if (op === "health") return json(200, { ok: true, customers: Object.keys(CUSTOMERS).length, operations: Object.keys(OPS) });
    if (op === "ledger" && parts[2]) {                       // for us: what the agent did for one customer
      return json(200, (await this.ctx.storage.get("c:" + parts[2])) || { calls: [] });
    }
    if (op === "reset" && parts[2] && request.method === "POST") {
      await this.ctx.storage.delete("c:" + parts[2]);
      return json(200, { reset: parts[2] });
    }
    const handler = OPS[op];
    if (!handler) return json(404, { error: "unknown_operation", operation: op });
    let body = {};
    if (request.method !== "GET") {
      try { body = await request.json(); } catch (e) { return json(400, { error: "invalid_json" }); }
    }
    for (const [k, v] of url.searchParams) if (!(k in body)) body[k] = v;
    const id = body.customer_id || parts[2];
    const customer = CUSTOMERS[id];
    if (!customer) return json(404, { error: "customer_not_found", customer_id: id });
    const key = "c:" + id;
    const state = (await this.ctx.storage.get(key)) || { calls: [] };
    let status, result;
    try { [status, result] = await handler(body, customer, state); }
    catch (e) { status = 500; result = { error: "mock_error", detail: String(e) }; }
    state.calls.push({ at: new Date().toISOString(), tool: op, body, status, result });
    await this.ctx.storage.put(key, state);
    return json(status, result);
  }
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") return new Response(null, { headers: { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*" } });
    const stub = env.BANK.get(env.BANK.idFromName("bank"));
    return stub.fetch(request);
  },
};
