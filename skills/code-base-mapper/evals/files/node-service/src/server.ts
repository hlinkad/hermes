import express from "express";
import { listUsers } from "./routes/users";

export const API_VERSION = "v1";

export class ApiServer {
  start(port: number) {
    const app = express();
    app.get("/health", healthRoute);
    app.get("/users", listUsers);
    return app.listen(port);
  }
}

export function healthRoute(_req: unknown, res: { json: (body: unknown) => void }) {
  res.json({ ok: true, version: API_VERSION });
}
