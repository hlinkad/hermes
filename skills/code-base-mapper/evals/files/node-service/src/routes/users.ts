export async function listUsers(_req: unknown, res: { json: (body: unknown) => void }) {
  res.json([{ id: "usr_1", name: "Ada" }]);
}
