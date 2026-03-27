import { cn } from "@/lib/utils";
import { CheckCircle2, Circle, ArrowRight } from "lucide-react";
import type { PipelineStage } from "@/lib/types";

const STAGES: { key: PipelineStage; label: string }[] = [
  { key: "ready-to-spec", label: "Ready to Spec" },
  { key: "spec-in-review", label: "Spec in Review" },
  { key: "ready-to-implement", label: "Ready to Implement" },
  { key: "code-in-review", label: "Code in Review" },
];

interface StageIndicatorProps {
  currentStage: PipelineStage;
  className?: string;
}

export function StageIndicator({ currentStage, className }: StageIndicatorProps) {
  const currentIndex = STAGES.findIndex((s) => s.key === currentStage);

  return (
    <div className={cn("flex items-center gap-1", className)}>
      {STAGES.map((stage, i) => {
        const isComplete = i < currentIndex;
        const isCurrent = i === currentIndex;

        return (
          <div key={stage.key} className="flex items-center gap-1">
            <div
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-colors",
                isComplete && "bg-primary/10 text-primary",
                isCurrent && "bg-primary text-primary-foreground",
                !isComplete && !isCurrent && "bg-muted text-muted-foreground"
              )}
            >
              {isComplete ? (
                <CheckCircle2 className="h-3.5 w-3.5" />
              ) : (
                <Circle className="h-3.5 w-3.5" />
              )}
              <span className="hidden sm:inline">{stage.label}</span>
            </div>
            {i < STAGES.length - 1 && (
              <ArrowRight
                className={cn(
                  "h-3.5 w-3.5 shrink-0",
                  i < currentIndex ? "text-primary/50" : "text-muted-foreground/30"
                )}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
