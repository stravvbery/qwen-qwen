import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { useState } from "react";
import { Copy, Check } from "lucide-react";

interface MarkdownProps {
  children: string;
}

function CodeBlock({ children, className }: { children: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  const lang = className?.replace(/^language-/, "") || "";
  return (
    <div className="relative group">
      <button
        type="button"
        onClick={() => {
          navigator.clipboard.writeText(children).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1200);
          });
        }}
        className="absolute right-2 top-2 inline-flex items-center gap-1 px-2 py-1 rounded-md bg-surface-3 text-text-muted text-xs opacity-0 group-hover:opacity-100 hover:text-text hover:bg-surface-3/90 transition"
        aria-label="Скопировать код"
      >
        {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
        {copied ? "Скопировано" : lang || "Код"}
      </button>
      <pre>
        <code className={className}>{children}</code>
      </pre>
    </div>
  );
}

export function Markdown({ children }: MarkdownProps) {
  return (
    <div className="prose-chat">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[[rehypeHighlight, { detect: true, ignoreMissing: true }]]}
        components={{
          pre({ children: pc }) {
            // react-markdown passes <code> as a child of <pre>. Pull it out so
            // our CodeBlock can render the copy button outside the <pre>.
            const child = Array.isArray(pc) ? pc[0] : pc;
            if (
              child &&
              typeof child === "object" &&
              "props" in child &&
              (child as { props: { className?: string; children?: unknown } }).props
            ) {
              const props = (child as { props: { className?: string; children?: unknown } })
                .props;
              const text = String(props.children ?? "").replace(/\n$/, "");
              return <CodeBlock className={props.className}>{text}</CodeBlock>;
            }
            return <pre>{pc}</pre>;
          },
          a({ children: ac, ...rest }) {
            return (
              <a {...rest} target="_blank" rel="noreferrer noopener">
                {ac}
              </a>
            );
          },
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
