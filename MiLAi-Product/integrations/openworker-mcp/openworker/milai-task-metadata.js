import crypto from "node:crypto"

const hostInstance = crypto.randomUUID()
const assistantByParent = new Map()

function nativeIdentifier(value, label) {
  if (typeof value !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$/.test(value)) {
    throw new Error(`MiLAi ${label} is unavailable`)
  }
  return value
}

function observedAt(value, label) {
  if (!Number.isSafeInteger(value) || value <= 0) {
    throw new Error(`MiLAi ${label} is unavailable`)
  }
  return new Date(value).toISOString()
}

export const MiLAiTaskMetadata = async () => ({
  event: async ({ event }) => {
    if (event.type !== "message.updated") return
    const info = event.properties?.info
    if (info?.role !== "assistant") return
    assistantByParent.set(`${info.sessionID}:${info.parentID}`, {
      id: nativeIdentifier(info.id, "assistant message"),
      observedAt: observedAt(info.time?.created, "assistant timestamp"),
    })
    if (assistantByParent.size > 512) {
      assistantByParent.delete(assistantByParent.keys().next().value)
    }
  },
  "chat.headers": async (input, output) => {
    const userMessage = nativeIdentifier(input.message?.id, "task operation")
    const assistant = assistantByParent.get(`${input.sessionID}:${userMessage}`)
    if (!assistant) throw new Error("MiLAi assistant message is unavailable")
    output.headers["X-MiLAi-Host-Instance"] = hostInstance
    output.headers["X-MiLAi-Task-Session"] = nativeIdentifier(
      input.sessionID,
      "task session",
    )
    output.headers["X-MiLAi-Task-Operation"] = userMessage
    output.headers["X-MiLAi-Assistant-Message"] = assistant.id
    output.headers["X-MiLAi-User-Observed-At"] = observedAt(
      input.message?.time?.created,
      "user timestamp",
    )
    output.headers["X-MiLAi-Assistant-Observed-At"] = assistant.observedAt
  },
})
