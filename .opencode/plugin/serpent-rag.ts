// serpent-rag.ts — OpenCode plugin: automatic Serpent context injection and
// static input linting. Installed by setup.sh (the python path is substituted).
//
// Hooks used:
//   chat.message                          remember the latest user text
//   experimental.chat.system.transform    inject a budgeted <serpent_context>
//   tool.execute.after                    static lint after write/edit of *.inp
//
// The plugin never throws: if python or the MCP installation is missing it
// degrades to a no-op.

const PYTHON = "__SERPENT_PYTHON__"
const BUDGET = 3500
const TIMEOUT_MS = 4000
const CACHE_TTL_MS = 10 * 60 * 1000

const SERPENTISH =
  /serpent|sss2|acelib|declib|nfylib|input card|criticality|burnup|depletion|detector|photon|neutron|критич|выгор|детектор|доз|распад|спектр|излучен|нейтрон|фотон|гамма|материал|геометри|сетк|изотоп/i

const INPUT_CARD = /(set\s+acelib|\bsurf\b|\bcell\b|\bmat\b|\bsrc\b|\bdet\b|\bene\b|\bdep\b)/i

type Entry = { text: string; at: number }
type Ctx = { text: string; at: number }

export const SerpentRag = async ({ $, directory }: any) => {
  const lastMessage = new Map<string, Entry>()
  const contextCache = new Map<string, Ctx>()

  async function buildContext(text: string): Promise<string> {
    try {
      const result =
        await $`${PYTHON} -m serpent2_mcp.rag query --text ${text} --workspace ${directory} --budget ${BUDGET}`
          .quiet()
          .nothrow()
          .timeout(TIMEOUT_MS)
      return result.stdout.toString()
    } catch {
      return ""
    }
  }

  async function lintFile(file: string): Promise<string> {
    try {
      const result =
        await $`${PYTHON} -m serpent2_mcp.lint ${file} --workspace ${directory}`
          .quiet()
          .nothrow()
          .timeout(TIMEOUT_MS)
      return result.stdout.toString()
    } catch {
      return ""
    }
  }

  function prune() {
    const now = Date.now()
    if (contextCache.size < 50) return
    for (const [key, value] of contextCache) {
      if (now - value.at > CACHE_TTL_MS) contextCache.delete(key)
    }
  }

  return {
    "chat.message": async (input: any, output: any) => {
      try {
        const text = (output.parts ?? [])
          .filter((part: any) => part.type === "text")
          .map((part: any) => part.text)
          .join("\n")
          .trim()
        if (text) lastMessage.set(input.sessionID, { text, at: Date.now() })
      } catch {
        /* no-op */
      }
    },

    "experimental.chat.system.transform": async (input: any, output: any) => {
      try {
        const entry = input?.sessionID ? lastMessage.get(input.sessionID) : undefined
        if (!entry?.text || !SERPENTISH.test(entry.text)) return
        const key = `${input.sessionID}:${entry.text}`
        let ctx = contextCache.get(key)
        if (!ctx || Date.now() - ctx.at > CACHE_TTL_MS) {
          ctx = { text: await buildContext(entry.text), at: Date.now() }
          contextCache.set(key, ctx)
          prune()
        }
        if (ctx.text.trim()) output.system.push(ctx.text.trim())
      } catch {
        /* no-op */
      }
    },

    "tool.execute.after": async (input: any, output: any) => {
      try {
        if (input.tool !== "write" && input.tool !== "edit") return
        const file: string | undefined = input.args?.filePath ?? input.args?.path
        if (!file || !/\.(inp|txt)$/i.test(file)) return
        if (input.tool === "write") {
          const content = String(input.args?.content ?? "")
          if (content && !INPUT_CARD.test(content)) return
        }
        const report = (await lintFile(file)).trim()
        if (report && !/OK \(no issues\)/i.test(report)) {
          output.output = `${output.output}\n\n<serpent-auto-lint>\n${report}\n</serpent-auto-lint>`
        }
      } catch {
        /* no-op */
      }
    },
  }
}

export default SerpentRag
