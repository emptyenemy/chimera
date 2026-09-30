import Markdown from "react-markdown"

export function ReleaseNotes({ children }: { children: string }) {
  return (
    <div className="flex flex-col gap-3 text-sm leading-relaxed break-words" data-testid="release-notes-content">
      <Markdown components={{
        h1: ({ children }) => <h3 className="text-lg font-semibold">{children}</h3>,
        h2: ({ children }) => <h3 className="text-lg font-semibold">{children}</h3>,
        h3: ({ children }) => <h4 className="font-semibold">{children}</h4>,
        ul: ({ children }) => <ul className="flex list-disc flex-col gap-2 pl-5">{children}</ul>,
        ol: ({ children }) => <ol className="flex list-decimal flex-col gap-2 pl-5">{children}</ol>,
        a: ({ children, href }) => <a href={href} target="_blank" rel="noopener noreferrer" className="underline underline-offset-4">{children}</a>,
      }}>{children}</Markdown>
    </div>
  )
}
