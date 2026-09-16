import crypto from "node:crypto"

const hostInstance = crypto.randomUUID()

function nativeIdentifier(value, label) {
  if (typeof value !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$/.test(value)) {
    throw new Error(`MiLAi ${label} is unavailable`)
  }
  return value
}

export const MiLAiTaskMetadata = async () => ({
  "chat.headers": async (input, output) => {
    output.headers["X-MiLAi-Host-Instance"] = hostInstance
    output.headers["X-MiLAi-Task-Session"] = nativeIdentifier(
      input.sessionID,
      "task session",
    )
    output.headers["X-MiLAi-Task-Operation"] = nativeIdentifier(
      input.message?.id,
      "task operation",
    )
  },
})
