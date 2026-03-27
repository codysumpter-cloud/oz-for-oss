"use client";

import { useMemo } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";

interface TocEntry {
  level: number;
  text: string;
  slug: string;
}

function extractHeadings(markdown: string): TocEntry[] {
  const headingRegex = /^(#{1,4})\s+(.+)$/gm;
  const entries: TocEntry[] = [];
  let match;
  while ((match = headingRegex.exec(markdown)) !== null) {
    const level = match[1].length;
    const text = match[2].trim();
    const slug = text
      .toLowerCase()
      .replace(/[^\w\s-]/g, "")
      .replace(/\s+/g, "-");
    entries.push({ level, text, slug });
  }
  return entries;
}

interface TableOfContentsProps {
  markdown: string;
  className?: string;
}

export function TableOfContents({ markdown, className = "" }: TableOfContentsProps) {
  const headings = useMemo(() => extractHeadings(markdown), [markdown]);

  if (headings.length === 0) return null;

  const minLevel = Math.min(...headings.map((h) => h.level));

  return (
    <ScrollArea className={`h-full ${className}`}>
      <nav className="space-y-1 text-sm" aria-label="Table of contents">
        <p className="font-semibold text-foreground mb-3 text-xs uppercase tracking-wider">
          On this page
        </p>
        {headings.map((heading, i) => (
          <a
            key={`${heading.slug}-${i}`}
            href={`#${heading.slug}`}
            className="block py-1 text-muted-foreground hover:text-foreground transition-colors truncate"
            style={{ paddingLeft: `${(heading.level - minLevel) * 12}px` }}
          >
            {heading.text}
          </a>
        ))}
      </nav>
    </ScrollArea>
  );
}
