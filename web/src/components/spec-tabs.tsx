"use client";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { MarkdownViewer } from "./markdown-viewer";
import { TableOfContents } from "./table-of-contents";
import { FileText, Wrench } from "lucide-react";
import { useState } from "react";

interface SpecTabsProps {
  productSpec: string | null;
  techSpec: string | null;
  className?: string;
}

export function SpecTabs({ productSpec, techSpec, className = "" }: SpecTabsProps) {
  const defaultTab = productSpec ? "product" : techSpec ? "tech" : "product";
  const [activeTab, setActiveTab] = useState(defaultTab);
  const activeContent = activeTab === "product" ? productSpec : techSpec;

  return (
    <div className={`flex gap-6 ${className}`}>
      <div className="flex-1 min-w-0">
        <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
          <TabsList className="mb-6">
            <TabsTrigger value="product" disabled={!productSpec} className="gap-2">
              <FileText className="h-4 w-4" />
              Product Spec
            </TabsTrigger>
            <TabsTrigger value="tech" disabled={!techSpec} className="gap-2">
              <Wrench className="h-4 w-4" />
              Tech Spec
            </TabsTrigger>
          </TabsList>
          <TabsContent value="product">
            {productSpec ? (
              <MarkdownViewer content={productSpec} />
            ) : (
              <div className="text-muted-foreground text-center py-12">
                No product spec available yet.
              </div>
            )}
          </TabsContent>
          <TabsContent value="tech">
            {techSpec ? (
              <MarkdownViewer content={techSpec} />
            ) : (
              <div className="text-muted-foreground text-center py-12">
                No tech spec available yet.
              </div>
            )}
          </TabsContent>
        </Tabs>
      </div>
      {activeContent && (
        <aside className="hidden xl:block w-56 shrink-0">
          <div className="sticky top-24">
            <TableOfContents markdown={activeContent} />
          </div>
        </aside>
      )}
    </div>
  );
}
