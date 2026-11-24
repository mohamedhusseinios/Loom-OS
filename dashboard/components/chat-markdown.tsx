"use client";

import { useRef, useState, type ReactNode } from "react";
import { Check, Copy } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { cn } from "@/lib/utils";
import "highlight.js/styles/github-dark.css";

type Variant = "default" | "muted" | "compact";

const variantClass: Record<Variant, string> = {
  default: "chat-md text-sm text-zinc-200",
  muted: "chat-md text-xs leading-relaxed text-zinc-500",
  compact: "chat-md text-[11px] leading-snug text-inherit",
};

function isSafeLinkHref(href: string | undefined): href is string {
  if (!href) return false;
  const trimmed = href.trim();
  const lower = trimmed.toLowerCase();
  if (trimmed.startsWith("/") && !trimmed.startsWith("//")) return true;
  return lower.startsWith("http:") || lower.startsWith("https:") || lower.startsWith("mailto:");
}

function CodeBlockPre(props: { children: ReactNode; copyLabel?: string; copiedLabel?: string }) {
  const { children, copyLabel = "Copy code", copiedLabel = "Copied" } = props;
  const preRef = useRef<HTMLPreElement>(null);
  const copyResetTimerRef = useRef<number | null>(null);
  const [copied, setCopied] = useState(false);

  async function copy() {
    const text = preRef.current?.textContent ?? "";
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      if (copyResetTimerRef.current !== null) window.clearTimeout(copyResetTimerRef.current);
      copyResetTimerRef.current = window.setTimeout(() => {
        setCopied(false);
        copyResetTimerRef.current = null;
      }, 1500);
    } catch {
      /* clipboard unavailable */
    }
  }

  return (
    <div className="group/code relative my-2">
      <button
        type="button"
        onClick={() => void copy()}
        title={copied ? copiedLabel : copyLabel}
        aria-label={copied ? copiedLabel : copyLabel}
        className="absolute end-1.5 top-1.5 z-10 inline-flex items-center gap-1 rounded border border-zinc-700 bg-zinc-900/90 px-1.5 py-0.5 text-[10px] text-zinc-400 opacity-0 transition-opacity hover:text-zinc-100 focus-visible:opacity-100 group-hover/code:opacity-100"
      >
        {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
        {copied ? copiedLabel : null}
      </button>
      <pre
        ref={preRef}
        className="overflow-x-auto rounded-md border border-zinc-800 bg-zinc-950/80 p-2 text-[0.85em]"
      >
        {children}
      </pre>
    </div>
  );
}

export function ChatMarkdown(props: { content: string; className?: string; variant?: Variant; copyCodeLabel?: string; copiedLabel?: string }) {
  const { content, className, variant = "default", copyCodeLabel, copiedLabel } = props;
  if (!content.trim()) return null;
  const codeCopyEnabled = variant !== "compact" && copyCodeLabel !== undefined && copiedLabel !== undefined;
  return (
    <div data-variant={variant} className={cn(variantClass[variant], "chat-md-root break-words", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[[rehypeHighlight, { detect: false }]]}
        components={{
          a: ({ href, children }) =>
            variant === "compact" ? (
              <span>{children}</span>
            ) : isSafeLinkHref(href) ? (
              <a href={href} target="_blank" rel="noreferrer" className="text-sky-400 underline underline-offset-2">
                {children}
              </a>
            ) : (
              <span>{children}</span>
            ),
          pre: ({ children }) =>
            codeCopyEnabled ? (
              <CodeBlockPre copyLabel={copyCodeLabel} copiedLabel={copiedLabel}>
                {children}
              </CodeBlockPre>
            ) : (
              <pre className="my-2 overflow-x-auto rounded-md border border-zinc-800 bg-zinc-950/80 p-2 text-[0.85em]">{children}</pre>
            ),
          code: ({ className: codeClass, children, ...rest }) => {
            const isBlock = Boolean(codeClass);
            if (isBlock) {
              return (
                <code className={cn(codeClass, "font-mono bg-transparent! p-0!")} {...rest}>
                  {children}
                </code>
              );
            }
            return (
              <code className="rounded bg-zinc-800 px-1 py-0.5 font-mono text-[0.9em] text-zinc-100" {...rest}>
                {children}
              </code>
            );
          },
          ul: ({ children }) => <ul className="my-1.5 list-disc space-y-0.5 ps-5">{children}</ul>,
          ol: ({ children }) => <ol className="my-1.5 list-decimal space-y-0.5 ps-5">{children}</ol>,
          li: ({ children }) => <li className="leading-relaxed">{children}</li>,
          h1: ({ children }) => <h1 className="mb-1 mt-2 text-[1.15em] font-semibold text-zinc-50">{children}</h1>,
          h2: ({ children }) => <h2 className="mb-1 mt-2 text-[1.05em] font-semibold text-zinc-50">{children}</h2>,
          h3: ({ children }) => <h3 className="mb-1 mt-2 text-[1em] font-medium text-zinc-100">{children}</h3>,
          p: ({ children }) => <p className="my-1.5 leading-relaxed">{children}</p>,
          blockquote: ({ children }) => (
            <blockquote className="my-1.5 border-s-2 border-zinc-600 ps-2 text-zinc-400">{children}</blockquote>
          ),
          table: ({ children }) => (
            <div className="my-2 overflow-x-auto">
              <table className="w-full border-collapse text-left text-[0.9em]">{children}</table>
            </div>
          ),
          th: ({ children }) => <th className="border border-zinc-700 bg-zinc-900 px-2 py-1 font-medium">{children}</th>,
          td: ({ children }) => <td className="border border-zinc-800 px-2 py-1">{children}</td>,
          hr: () => <hr className="my-2 border-zinc-800" />,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}