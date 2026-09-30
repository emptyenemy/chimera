const bundled = import.meta.glob("../../../release-notes/*.md", {
  query: "?raw", import: "default", eager: true,
}) as Record<string, string>

export function releaseNotes(version: string, body: string, lang: "ru" | "en"): string {
  const key = `../../../release-notes/${version.replace(/^v/, "")}.${lang}.md`
  if (bundled[key]) return bundled[key].trim()
  const start = `<!-- chimera:${lang} -->`
  const end = `<!-- /chimera:${lang} -->`
  const index = body.indexOf(start)
  if (index !== -1) {
    const text = body.slice(index + start.length)
    const stop = text.indexOf(end)
    if (stop !== -1) return text.slice(0, stop).trim()
  }
  return body.trim()
}
