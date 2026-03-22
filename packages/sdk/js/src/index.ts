export * from "./client.js"
export * from "./server.js"

import { createMalibuClient } from "./client.js"
import { createMalibuServer } from "./server.js"
import type { ServerOptions } from "./server.js"

export async function createMalibu(options?: ServerOptions) {
  const server = await createMalibuServer({
    ...options,
  })

  const client = createMalibuClient({
    baseUrl: server.url,
  })

  return {
    client,
    server,
  }
}
