"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";

interface MarkdownViewerProps {
  content: string;
  className?: string;
}

export function MarkdownViewer({ content, className = "" }: MarkdownViewerProps) {
  return (
    <div className={`prose prose-neutral dark:prose-invert max-w-none ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          h1: ({ children, ...props }) => (
            <h1 className="text-2xl font-bold mt-8 mb-4 pb-2 border-b border-border" {...props}>
              {children}
            </h1>
          ),
          h2: ({ children, ...props }) => (
            <h2 className="text-xl font-semibold mt-6 mb-3 pb-1 border-b border-border/50" {...props}>
              {children}
            </h2>
          ),
          h3: ({ children, ...props }) => (
            <h3 className="text-lg font-semibold mt-5 mb-2" {...props}>
              {children}
            </h3>
          ),
          h4: ({ children, ...props }) => (
            <h4 className="text-base font-semibold mt-4 mb-2" {...props}>
              {children}
            </h4>
          ),
          code: ({ className: codeClassName, children, ...props }) => {
            const isInline = !codeClassName;
            if (isInline) {
              return (
                <code
                  className="bg-muted px-1.5 py-0.5 rounded text-sm font-mono"
                  {...props}
                >
                  {children}
                </code>
              );
            }
            return (
              <code className={`${codeClassName || ""} text-sm`} {...props}>
                {children}
              </code>
            );
          },
          pre: ({ children, ...props }) => (
            <pre
              className="bg-muted/50 border border-border rounded-lg p-4 overflow-x-auto my-4"
              {...props}
            >
              {children}
            </pre>
          ),
          a: ({ children, href, ...props }) => (
            <a
              href={href}
              className="text-primary underline underline-offset-4 hover:text-primary/80 transition-colors"
              target={href?.startsWith("http") ? "_blank" : undefined}
              rel={href?.startsWith("http") ? "noopener noreferrer" : undefined}
              {...props}
            >
              {children}
            </a>
          ),
          ul: ({ children, ...props }) => (
            <ul className="list-disc pl-6 my-3 space-y-1" {...props}>
              {children}
            </ul>
          ),
          ol: ({ children, ...props }) => (
            <ol className="list-decimal pl-6 my-3 space-y-1" {...props}>
              {children}
            </ol>
          ),
          li: ({ children, ...props }) => (
            <li className="leading-relaxed" {...props}>
              {children}
            </li>
          ),
          blockquote: ({ children, ...props }) => (
            <blockquote
              className="border-l-4 border-primary/30 pl-4 my-4 italic text-muted-foreground"
              {...props}
            >
              {children}
            </blockquote>
          ),
          table: ({ children, ...props }) => (
            <div className="overflow-x-auto my-4">
              <table className="min-w-full border border-border rounded-lg" {...props}>
                {children}
              </table>
            </div>
          ),
          th: ({ children, ...props }) => (
            <th className="bg-muted px-4 py-2 text-left font-semibold border-b border-border" {...props}>
              {children}
            </th>
          ),
          td: ({ children, ...props }) => (
            <td className="px-4 py-2 border-b border-border/50" {...props}>
              {children}
            </td>
          ),
          hr: (props) => <hr className="my-6 border-border" {...props} />,
          p: ({ children, ...props }) => (
            <p className="leading-7 my-3" {...props}>
              {children}
            </p>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
