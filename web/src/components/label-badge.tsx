import type { GitHubLabel } from "@/lib/types";

function getContrastColor(hexColor: string): string {
  const r = parseInt(hexColor.slice(0, 2), 16);
  const g = parseInt(hexColor.slice(2, 4), 16);
  const b = parseInt(hexColor.slice(4, 6), 16);
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return luminance > 0.5 ? "#1f2328" : "#ffffff";
}

interface LabelBadgeProps {
  label: GitHubLabel;
}

export function LabelBadge({ label }: LabelBadgeProps) {
  const bg = `#${label.color}`;
  const fg = getContrastColor(label.color);

  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium leading-tight"
      style={{ backgroundColor: bg, color: fg }}
    >
      {label.name}
    </span>
  );
}
